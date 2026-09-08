"""Regression guard for P1.1: D/ST and K were vastly overvalued on the value board.

The defect was never in the D/ST and K numbers, which is why clamping them would have
been the wrong fix. Replacement level was computed as "best non-starter", which is the
waiver wire only in a league with no bench. League B drafts 16 rounds against 9 starting
slots, so 56 of its 128 picks are bench players who are NOT on the wire. Counting them
put the RB baseline at RB17 and the WR baseline at WR25 -- 30-50 points too generous --
while leaving D/ST and K correct at 9, because nobody rosters a backup D/ST. The board
then ranked the top D/ST 33rd overall and named D/ST and K its eleven biggest targets.

These run against `espn_board_projections.json`: the real top-80-per-position projection
curve captured from the League B board, so the shape being asserted is the shape that
actually shipped, not an invented one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audible.config import LeagueConfig
from audible.models import PlayerProjection
from audible.value import compute_vorp, replacement_levels

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SPECIALIST = ("DEF", "K")


@pytest.fixture(scope="module")
def board_projections() -> list[PlayerProjection]:
    rows = json.loads((FIXTURES / "espn_board_projections.json").read_text())
    return [
        PlayerProjection(
            player_id=r["player_id"], name=r["name"], primary_position=r["position"],
            eligible_positions=frozenset({r["position"]}), team=None, points=r["points"],
        )
        for r in rows
    ]


def _vorp_by_id(players: list[PlayerProjection], config: LeagueConfig) -> dict[str, float]:
    entries, _ = compute_vorp(players, config)
    return {e.projection.player_id: e.vorp for e in entries}


def _nth_at(players: list[PlayerProjection], position: str, n: int) -> PlayerProjection:
    ranked = sorted(
        (p for p in players if p.primary_position == position),
        key=lambda p: (-p.points, p.player_id),
    )
    return ranked[n - 1]


def test_specialist_vorp_never_beats_a_mid_tier_starter(
    espn_config: LeagueConfig, board_projections: list[PlayerProjection]
) -> None:
    """No D/ST or K may be worth more than the 24th RB or the 24th WR.

    This is the bug stated as an invariant. RB24 and WR24 are ordinary starters -- a
    weekly RB2/WR2 in an 8-team league -- and a position that puts exactly one flat,
    streamable body in one lineup slot cannot outrank them. Nothing here is a clamp: the
    engine is free to price D/ST however it likes, it just has to lose this comparison.
    """
    vorp = _vorp_by_id(board_projections, espn_config)
    floor = min(
        vorp[_nth_at(board_projections, "RB", 24).player_id],
        vorp[_nth_at(board_projections, "WR", 24).player_id],
    )
    worst = max(
        (p for p in board_projections if p.primary_position in SPECIALIST),
        key=lambda p: vorp[p.player_id],
    )
    assert vorp[worst.player_id] < floor, (
        f"{worst.name} ({worst.primary_position}) VORP {vorp[worst.player_id]:.1f} "
        f">= mid-tier starter floor {floor:.1f} -- D/ST and K are inflated again"
    )


def test_no_specialist_in_the_first_eight_rounds(
    espn_config: LeagueConfig, board_projections: list[PlayerProjection]
) -> None:
    """A D/ST or K inside the first 8 rounds of picks is indefensible at any scoring."""
    entries, _ = compute_vorp(board_projections, espn_config)
    early = espn_config.num_teams * 8
    offenders = [
        (i, e.projection.name, e.projection.primary_position)
        for i, e in enumerate(entries[:early], 1)
        if e.projection.primary_position in SPECIALIST
    ]
    assert not offenders, f"D/ST or K inside the first {early} picks: {offenders}"


def test_the_bench_is_what_holds_the_invariant_up(
    espn_config: LeagueConfig, board_projections: list[PlayerProjection]
) -> None:
    """Pin the MECHANISM, so nobody can restore the bug by zeroing the config field.

    With the bench priced out, the same engine over the same players puts a D/ST above
    the mid-tier floor again. That is the defect, reproduced on demand.
    """
    broken = espn_config.model_copy(update={"replacement_bench_slots": 0})
    vorp = _vorp_by_id(board_projections, broken)
    floor = min(
        vorp[_nth_at(board_projections, "RB", 24).player_id],
        vorp[_nth_at(board_projections, "WR", 24).player_id],
    )
    best_specialist = max(
        vorp[p.player_id] for p in board_projections if p.primary_position in SPECIALIST
    )
    assert best_specialist > floor


def test_replacement_lands_where_the_market_drafts(
    espn_config: LeagueConfig, board_projections: list[PlayerProjection]
) -> None:
    """Baselines must sit at the waiver line, not the starter line.

    THIS TEST PINNED THE DEFECT IT WAS MEANT TO GUARD, and the way it did so is worth naming.
    It named RB, WR and TE and never named QB. It also asserted `drafted == teams * rounds`,
    and with the other five positions pinned that conservation forces QB to exactly 8 -- so it
    did not merely omit QB, it PINNED QB at the defective value without ever mentioning it.
    That is worse than an omission: the failure it produces when the defect is fixed reads as
    three unrelated count changes, and nothing points at the quarterback. Every position is
    named explicitly now, specialists included.

    THE ANCHOR ALSO CHANGED, because the old one was unsourced. This docstring used to cite
    "the market's own first 128 picks (43 RB / 53 WR / 16 QB / 16 TE, no D/ST or K)" as "the
    only ground truth for how many of each position get drafted". Measured against every FFC
    board pinned in this repo (2021-2025), that composite matches no season: RB runs 39-50,
    WR 48-58, QB 15-18, TE 10-13. Worse, ADP is the wrong instrument for the question -- its
    top 128 holds ZERO kickers while the five completed league-6012 drafts take 8.2 of them --
    about one per team every year, and 9 in 2024.

    The anchor is now those completed drafts, which are pinned in the same cache and are the
    actual answer to "how many of each position get drafted":

        rostered inside 128 picks, mean of 2021-2025:
        QB 13.0   RB 40.0   WR 48.0   TE 10.4   K 8.2   DEF 8.4

    What this fixture produces is pinned exactly below, and it does NOT equal that anchor --
    the fixture is one season's projection curve and the anchor is a five-season mean of a
    different quantity. The pins are there to make any further change to the bench split fail
    loudly and say which positions moved; they are not a claim that the rule reproduces the
    market. RB 32 against a market 40.0 and TE 16 against 10.4 are both still wrong, and the
    log in `sim/runs/b7-iterations.md` records that they are.
    """
    levels = replacement_levels(board_projections, espn_config)
    teams = espn_config.num_teams

    for position in SPECIALIST:
        assert levels[position].rostered == teams
        assert levels[position].starters_used == teams

    # QB IS THE ONE THIS TEST USED TO PIN SILENTLY, through the conservation assertion below
    # rather than by name. A 1-QB league starts 8 and the real drafts roster 13, so a baseline
    # at the starting-slot count is the defect and 8 must fail here, visibly.
    assert levels["QB"].rostered == 16
    assert levels["QB"].rostered > levels["QB"].starters_used, (
        "QB got starters only, which is the pre-B7 defect: `rostered_counts` grouped a 1-QB "
        "league's quarterback with D/ST and K because all three occupy one starting slot"
    )

    assert levels["RB"].rostered == 32
    assert levels["WR"].rostered == 48
    assert levels["TE"].rostered == 16
    # Every position a team keeps its own backups for must clear its own starting demand.
    for position in ("QB", "RB", "WR", "TE"):
        assert levels[position].rostered > levels[position].starters_used

    drafted = sum(lvl.rostered for lvl in levels.values())
    rounds = len(espn_config.starting_slots) + espn_config.replacement_bench_slots
    assert drafted == teams * rounds


def test_bench_slots_default_to_off(mini_config: LeagueConfig) -> None:
    """A config that says nothing gets the old starters-only baseline, unchanged."""
    assert mini_config.replacement_bench_slots == 0
