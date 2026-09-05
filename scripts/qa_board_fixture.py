"""A pinned draft board, so QA is deterministic and offline.

The QA loop must never depend on what Sleeper/nflverse return today: a UI regression and
a market move would be indistinguishable, and a red run would not reproduce tomorrow.
So the board is built ONCE from live data, frozen to JSON here, and every later QA run
loads that frozen board instead of calling `build_board`.

    uv run --extra nflverse python scripts/qa_board_fixture.py --league espn_davis_drive

Regenerating is a deliberate, out-of-loop act -- it changes the oracle's input, so it is
committed as its own change and the suite is re-run against it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# Bumped whenever DraftEntry's fields change, so a stale fixture fails loudly at load
# instead of silently serving a board that is missing a column the cockpit renders.
# v2 adds the pinned usage table. Usage is display-only, but pinning it matters for the
# same reason the board is pinned: otherwise a nflverse cache refresh silently changes
# what QA measures, and a red run stops reproducing.
SCHEMA_VERSION = 2


def fixture_path(league: str) -> Path:
    return FIXTURE_DIR / f"qa-board-{league}.json"


def dump_board(board) -> dict:
    from dataclasses import fields

    names = [f.name for f in fields(type(board.entries[0]))] if board.entries else []
    rows = []
    for e in board.entries:
        row = {}
        for n in names:
            v = getattr(e, n)
            if isinstance(v, frozenset):
                v = sorted(v)
            elif isinstance(v, tuple):
                v = list(v)
            row[n] = v
        rows.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "league_key": board.league_key,
        "fields": names,
        "entries": rows,
    }


USAGE_FIELDS = ("target_share", "air_yards_share", "route_participation",
                "snap_share", "depth_slot")


def dump_usage(usage) -> dict:
    """Only the players ON this board -- the full table is 6,378 rows of mostly nobody."""
    return {
        "by_player_id": {
            pid: {f: getattr(ctx, f) for f in USAGE_FIELDS}
            for pid, ctx in usage.by_player_id.items()
        },
        "bye_by_team": dict(usage.bye_by_team),
        "missing_sources": list(usage.missing_sources),
    }


def load_usage_table(league: str, path: Path | None = None):
    """The pinned usage table, rebuilt into a real UsageTable."""
    from audible.draft.usage import UsageContext, UsageTable

    p = path or fixture_path(league)
    blob = json.loads(p.read_text(encoding="utf-8"))
    raw = blob.get("usage") or {}
    return UsageTable(
        by_player_id={
            pid: UsageContext(**{f: row.get(f) for f in USAGE_FIELDS})
            for pid, row in (raw.get("by_player_id") or {}).items()
        },
        bye_by_team={k: int(v) for k, v in (raw.get("bye_by_team") or {}).items()},
        missing_sources=tuple(raw.get("missing_sources") or ()),
    )


def load_board(league: str, path: Path | None = None):
    """Rebuild a DraftBoard from the pinned JSON, or die loudly."""
    from audible.draft.board import DraftBoard, DraftEntry

    p = path or fixture_path(league)
    if not p.exists():
        raise SystemExit(
            f"no pinned board at {p}\n"
            f"generate it once with:  uv run --extra nflverse python "
            f"scripts/qa_board_fixture.py --league {league}"
        )
    blob = json.loads(p.read_text(encoding="utf-8"))
    if blob.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(
            f"pinned board {p} is schema v{blob.get('schema_version')}, "
            f"this code wants v{SCHEMA_VERSION} -- regenerate it"
        )

    from dataclasses import fields

    want = {f.name for f in fields(DraftEntry)}
    have = set(blob["fields"])
    if want != have:
        raise SystemExit(
            f"pinned board {p} does not match DraftEntry: "
            f"missing={sorted(want - have)} extra={sorted(have - want)} -- regenerate it"
        )

    entries = [
        DraftEntry(
            **{
                **row,
                "eligible_positions": frozenset(row["eligible_positions"]),
                "flags": tuple(row["flags"]),
            }
        )
        for row in blob["entries"]
    ]
    return DraftBoard(league_key=blob["league_key"], entries=entries)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    args = ap.parse_args()

    from audible.config.loader import load_all_leagues
    from audible.draft.board import build_board

    cfg = load_all_leagues()[args.league]
    print(f"building a live board for {args.league} (this hits the network/disk cache)...")
    board = build_board(cfg)

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    out = fixture_path(args.league)
    from audible.draft.usage import load_usage

    print("loading usage context...")
    usage = load_usage()
    if usage.missing_sources:
        raise SystemExit(
            f"refusing to pin a degraded usage table; missing {usage.missing_sources}")
    on_board = {e.player_id for e in board.entries}
    trimmed = type(usage)(
        by_player_id={k: v for k, v in usage.by_player_id.items() if k in on_board},
        bye_by_team=usage.bye_by_team,
        missing_sources=usage.missing_sources,
    )
    blob = dump_board(board)
    blob["usage"] = dump_usage(trimmed)
    out.write_text(json.dumps(blob, separators=(",", ":"), sort_keys=True),
                   encoding="utf-8")
    print(f"pinned {len(board.entries)} entries -> {out} ({out.stat().st_size / 1024:.0f} KB)")

    check = load_board(args.league)
    assert [e.player_id for e in check.entries] == [e.player_id for e in board.entries]
    assert [e.vorp_rank for e in check.entries] == [e.vorp_rank for e in board.entries]
    u = load_usage_table(args.league)
    have = sum(1 for c in u.by_player_id.values() if c.target_share is not None)
    print(f"round-trip verified: ids and vorp ranks identical; "
          f"usage rows={len(u.by_player_id)} (target_share on {have}), "
          f"byes={len(u.bye_by_team)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
