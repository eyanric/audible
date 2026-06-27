from __future__ import annotations

from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.cheatsheet import build_cheatsheet, compute_tiers, render_csv, render_html


def test_compute_tiers_breaks_at_cliffs() -> None:
    # gaps: 2,2,2,24,2,2,26 -> avg ~8.6, threshold ~12 -> breaks after the 24 and 26 drops
    pts = [100, 98, 96, 94, 70, 68, 66, 40]
    assert compute_tiers(pts, gap_factor=1.4, min_gap=8, depth=48) == [1, 1, 1, 1, 2, 2, 2, 3]


def test_compute_tiers_edge_cases() -> None:
    assert compute_tiers([]) == []
    assert compute_tiers([50.0]) == [1]
    # a smooth slope with no cliff stays one tier
    assert compute_tiers([100, 99, 98, 97, 96], min_gap=8) == [1, 1, 1, 1, 1]


def _entry(pid: str, pos: str, pts: float, vrank: int, srank: int, value: int) -> DraftEntry:
    return DraftEntry(
        player_id=pid, name=f"Player {pid}", position=pos, team="X", model="consensus",
        points=pts, modeled_xfp=0.0, carried=0.0, consensus=pts, vorp=pts, vorp_rank=vrank,
        scarcity=pts, scarcity_rank=srank, adp=float(vrank + value), adp_rank=vrank + value,
        value=value, flags=("opp+30",),
    )


def test_renders_csv_and_html(sleeper_config) -> None:
    board = DraftBoard(
        league_key="x",
        entries=[
            _entry("a", "QB", 300, 1, 1, +20),
            _entry("b", "QB", 260, 2, 2, -15),
            _entry("c", "RB", 280, 3, 3, +5),
        ],
    )
    cs = build_cheatsheet(board, sleeper_config, "2026-06-27")
    csv_text = render_csv(cs)
    assert "overall,pos,pos_tier,name" in csv_text
    assert "Player a" in csv_text and "TARGET" in csv_text and "REACH" in csv_text

    html_text = render_html(cs)
    assert "<table" in html_text and "Player a" in html_text and "Tier 1" in html_text
