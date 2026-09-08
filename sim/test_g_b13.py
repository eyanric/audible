"""GATES for B13's `real_board = "production"`: the seat drafts the cockpit's own board.

WHAT THIS SESSION FIXED, and why it needed a gate of its own. `sim/seat.board_from_season`
builds a board whose value is linear in ADP rank, so the board's order IS the market's order.
Every `real` number from B2 through B12 was measured on it, and the arm was BYTE-IDENTICAL
across all of them -- including audible#77 and audible#78, two sessions that spent themselves
changing replacement level. Nothing either of them could change reaches a board that is a
relabelling of ADP, so the arm named "the cockpit's own path" was the one arm in the run
guaranteed not to move, and two sessions optimised against a number the cockpit does not
compute.

`test_the_production_board_moves_when_replacement_moves` IS THE GATE ON THE WHOLE SESSION. It
asserts both halves: that the market board does not respond to a replacement-depth change, and
that the production board does. If the first half ever fails, `board_from_season` has stopped
being a relabelling of ADP and the B2-B12 results need re-reading. If the second fails, this
session's change is not wired to anything and B13 measured nothing, exactly as B11 and B12 did.

WHAT THIS FILE DOES NOT CLAIM. That the production board is BETTER. It is measurably a
running-back monoculture on vintage FFA projections -- 20 to 22 of the first 24 board slots in
2022, 2023 and 2024 -- which is the same class of positional artifact `board_from_season`'s own
docstring records for a linear curve, with the positions swapped. That is a property of
`compute_vorp` over this pool and this rulebook, it is `audible_transform`'s known ordering,
and `sim/runs/b13-real.md` reports it. A gate that asserted the board looked sensible would be
asserting a preference.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.slow

# One season is enough for every structural claim here and each board costs 1.4-2.3 seconds to
# build. The depth-response gate uses two, because "it moved" is worth confirming twice.
SEASON = 2023
SEASONS = (2023, 2024)


def _require(name: str) -> Path:
    for root in (SIM_CACHE, LIVE_CACHE):
        if (root / name).exists():
            return root / name
    pytest.skip(f"{name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}")


@pytest.fixture(scope="module")
def mods():
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    from . import boards, markets, room, roundtrip, runner, seat, weekly

    _require("nflverse/ff_playerids.parquet")
    markets.set_active("ffc_12_std")
    for season in SEASONS:
        _require(f"ffc_adp_standard_8_{season}.json")
    return boards, markets, room, roundtrip, runner, seat, weekly


@pytest.fixture(scope="module")
def built(mods):
    """The FFA-source boards for both seasons, built once. The `SeasonBoards.board` is new."""
    boards, _markets, _room, roundtrip, _runner, _seat, weekly = mods
    league = weekly.league_config()
    return {
        season: boards.build(
            season, league, source=boards.FFA_SOURCE, deltas=roundtrip.HISTORICAL_DELTAS
        )
        for season in SEASONS
    }


def test_the_production_board_is_the_object_build_board_from_lines_returns(mods, built) -> None:
    """`SeasonBoards.board` must be the production object, not something rebuilt beside it.

    `sim/boards.build` has always called `build_board_from_lines(config, projected.lines)` --
    that is where `compute_vorp` runs and where `replacement` in the artifact comes from -- and
    then discarded the object after reading rank columns off it. The whole of B13's change is
    keeping it. So the assertion is identity of CONTENT with the reported replacement levels:
    if the board were rebuilt separately, or built from different lines, these would drift.
    """
    _boards, _markets, _room, _roundtrip, _runner, _seat, _weekly = mods
    board = built[SEASON].board
    assert board is not None, "SeasonBoards.board is None; the production object was dropped"
    assert board.entries, "the production board is empty"
    assert len(board.entries) > built[SEASON].pool // 2, (
        f"the production board carries {len(board.entries)} entries against a projected pool "
        f"of {built[SEASON].pool}; it was not built from the run's own lines"
    )
    # `vorp_rank` is dense and total over the FULL pool, tail included. That is the property
    # that makes dropping the tail afterwards safe: replacement level was found over everyone.
    ranks = sorted(e.vorp_rank for e in board.entries)
    assert ranks == list(range(1, len(ranks) + 1)), (
        "vorp_rank is not a dense 1..N over the full pool, so replacement level was not "
        "computed over the pool the projection supplied"
    )


def test_the_production_board_drops_the_tail_and_keeps_every_draftable_row(mods, built) -> None:
    """The seat and the room must see the same pool, or the comparison spans two universes.

    `sim/ffa.build` supplies a pool far larger than the room's board -- 595 lines against 192
    rows in 2023 -- because replacement level needs somewhere to find a baseline. Those extra
    players are keyed `ffa:<mfl id>` and the room has never heard of them: `AudibleSeat.pick`
    resolves one to index -1 and the seat FORFEITS the pick. `_order_by` filters the same tail
    for the board arms and this is the same filter for the seat.
    """
    _boards, _markets, room, _roundtrip, _runner, seat, _weekly = mods
    season_board = room.load_board(SEASON)
    cut = seat.production_board(built[SEASON].board, season_board)

    draftable = {f"ffc{r.rank:04d}" for r in season_board.rows}
    assert {e.player_id for e in cut.entries} == draftable, (
        "the seat's board and the room's board are not the same set of players"
    )
    assert len(cut.entries) < len(built[SEASON].board.entries), (
        "nothing was dropped, so the undraftable tail is still reachable by `the_call`"
    )
    assert [e.vorp_rank for e in cut.entries] == sorted(e.vorp_rank for e in cut.entries), (
        "entries are not sorted by vorp_rank, which is the DraftBoard contract"
    )
    # `value` is ADP rank minus a DENSE value rank over the same population. Production
    # re-ranks for exactly this reason: a sparse rank makes `value` measure pool size, and
    # `effective_score` reads `value`.
    for place, entry in enumerate(cut.entries, start=1):
        if entry.adp_rank is not None:
            assert entry.value == entry.adp_rank - place, (
                f"{entry.name}'s value is {entry.value} against adp_rank {entry.adp_rank} at "
                f"place {place}; it was carried from the full pool rather than recomputed"
            )


def test_the_shuffle_moves_value_and_nothing_else(mods, built) -> None:
    """G6b is worthless if the shuffle changes anything but the value ordering.

    `real - shuffle` is a statement about VALUE ORDERING, so the permutation must move a whole
    value bundle from one player to another while position, team, eligibility and ADP stay
    welded to the player. A shuffle that moved ADP would change which players the room reaches
    past; one that moved position would change what the seat can start.
    """
    _boards, _markets, room, _roundtrip, _runner, seat, _weekly = mods
    season_board = room.load_board(SEASON)
    plain = seat.production_board(built[SEASON].board, season_board)
    shuffled = seat.production_board(
        built[SEASON].board, season_board, shuffle=random.Random(0)
    )

    assert {e.player_id for e in plain.entries} == {e.player_id for e in shuffled.entries}
    before = {e.player_id: e for e in plain.entries}
    for entry in shuffled.entries:
        was = before[entry.player_id]
        assert entry.position == was.position, entry.name
        assert entry.team == was.team, entry.name
        assert entry.eligible_positions == was.eligible_positions, entry.name
        assert entry.adp == was.adp and entry.adp_rank == was.adp_rank, entry.name

    order_before = [e.player_id for e in plain.entries]
    order_after = [e.player_id for e in shuffled.entries]
    fixed = sum(1 for a, b in zip(order_before, order_after, strict=True) if a == b)
    assert fixed < len(order_before) // 10, (
        f"the shuffle left {fixed} of {len(order_before)} players in place, so it is not a "
        f"permutation of the value ordering"
    )
    # The multiset of values is preserved -- a shuffle must not invent or destroy value.
    assert sorted(e.points for e in plain.entries) == sorted(
        e.points for e in shuffled.entries
    ), "the shuffle changed the distribution of points, not just who holds which"


def test_the_production_board_moves_when_replacement_moves(mods, built) -> None:
    """THE GATE ON THE WHOLE SESSION. Both halves, because each one alone is uninformative.

    audible#77 and audible#78 each changed `rostered_counts` and each reported `real` unmoved,
    and neither could say whether that was a result or a wiring defect. It was a wiring defect:
    the seat's board is linear in ADP rank, and no replacement level can reach it. This asserts
    the two facts that separate those explanations, using audible#78's own depth table
    (QB 14, RB 43, WR 35, TE 20) as the perturbation.

    Measured when this gate was written, seat board order under that change against main's:

        season   market board          production board
        2023     192/192 unchanged      30/192 unchanged
        2024     180/180 unchanged      38/180 unchanged

    and the largest single move is a quarterback, Kyler Murray 127 -> 79 in 2024. That is the
    same direction and the same order of magnitude as the live-board measurement audible#77
    recorded on the 2026 `espn_davis_drive` lines -- Josh Allen 28 -> 14, Joe Burrow 108 -> 63 --
    which is the check that this path is the cockpit's and not a lookalike.
    """
    boards, _markets, room, roundtrip, _runner, seat, weekly = mods
    from audible.value import replacement

    league = weekly.league_config()
    original = replacement.rostered_counts

    def deeper(players, config, starters):
        counts = original(players, config, starters)
        counts.update({"QB": 14, "RB": 43, "WR": 35, "TE": 20})
        return counts

    for season in SEASONS:
        season_board = room.load_board(season)
        market_before = [
            e.player_id for e in seat.board_from_season(season_board, league).entries
        ]
        production_before = [
            e.player_id for e in seat.production_board(built[season].board, season_board).entries
        ]

        replacement.rostered_counts = deeper
        try:
            rebuilt = boards.build(
                season, league, source=boards.FFA_SOURCE,
                deltas=roundtrip.HISTORICAL_DELTAS,
            )
            market_after = [
                e.player_id for e in seat.board_from_season(season_board, league).entries
            ]
            production_after = [
                e.player_id for e in seat.production_board(rebuilt.board, season_board).entries
            ]
        finally:
            replacement.rostered_counts = original

        assert market_before == market_after, (
            f"{season}: the MARKET board responded to a replacement-depth change. It is "
            f"documented as linear in ADP rank and every `real` number from B2 to B12 was "
            f"measured on that basis; if it now moves, those results need re-reading."
        )
        held = sum(
            1 for a, b in zip(production_before, production_after, strict=True) if a == b
        )
        assert held < len(production_before) // 2, (
            f"{season}: the PRODUCTION board held {held} of {len(production_before)} places "
            f"under a full depth change, so `real` is still not wired to replacement level "
            f"and this session measured what audible#77 and audible#78 measured, which is "
            f"nothing."
        )


def test_a_production_board_over_an_invented_projection_is_refused(mods, tmp_path) -> None:
    """`real_board = "production"` with `projection = "walkforward"` must fail preflight.

    The production board is the cockpit's path over REAL vintage projections. Run over a
    projection this harness fitted from prior seasons it is the same value engine over a curve
    the harness invented -- which `sim/seat.board_from_season` documents the measured cost of,
    and which would be reported under a name claiming it was the cockpit's board.
    """
    _boards, _markets, _room, _roundtrip, runner, _seat, _weekly = mods
    config = tmp_path / "bad.toml"
    config.write_text(
        "[run]\n"
        'name = "bad"\n'
        "seasons = [2023]\n"
        "seed_start = 0\n"
        "seed_count = 1\n"
        'projection = "walkforward"\n'
        'real_board = "production"\n'
        'arms = ["real", "shuffle", "bot", "adp"]\n'
        "seat = 6\n"
        'league = "espn_davis_drive"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as caught:
        runner.load_config(config)
    assert "real_board" in str(caught.value), caught.value


def test_an_unknown_real_board_is_refused(mods, tmp_path) -> None:
    """A typo must fail loudly rather than silently selecting the default."""
    _boards, _markets, _room, _roundtrip, runner, _seat, _weekly = mods
    config = tmp_path / "typo.toml"
    config.write_text(
        "[run]\n"
        'name = "typo"\n'
        "seasons = [2023]\n"
        "seed_start = 0\n"
        "seed_count = 1\n"
        'projection = "ffa"\n'
        'real_board = "prodcution"\n'
        'arms = ["real", "shuffle", "bot", "adp"]\n'
        "seat = 6\n"
        'league = "espn_davis_drive"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as caught:
        runner.load_config(config)
    assert "prodcution" in str(caught.value), caught.value


def test_the_setting_reaches_the_config_hash(mods) -> None:
    """Two runs that differ only in `real_board` must not share a checkpoint.

    Every field that changes what a UNIT computes belongs in the hash. B8 found four that were
    silently missing and `--resume` would have appended one experiment's units to another's
    file. This one changes what every non-board arm computes, which is most of the run.
    """
    _boards, _markets, room, _roundtrip, runner, seat, _weekly = mods
    common = {
        "name": "h", "seasons": (2023,), "seeds": (0,),
        "arms": ("real", "shuffle", "bot", "adp"), "seat": 6,
        "league": "espn_davis_drive", "fit_seasons": tuple(room.SEASONS), "raw": {},
    }
    market = runner.RunConfig(**common, real_board=seat.MARKET_BOARD)
    production = runner.RunConfig(**common, real_board=seat.PRODUCTION_BOARD)
    assert market.config_hash != production.config_hash, (
        "two runs differing only in which board the seat drafts share a config hash, so a "
        "checkpoint from one would resume into the other"
    )
