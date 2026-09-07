"""TASK B4/2 -- four boards over one player universe, differing only in how they order it.

THE WHOLE DESIGN IS THAT THE PROJECTION IS HELD CONSTANT. `points_greedy` and
`audible_transform` are two orderings read off ONE `DraftBoard` built from ONE set of
`RawPlayerLine`s, so their difference cannot be a difference in projection -- there is only one
projection object and its digest is written into the artifact. That is G4, and building both
arms from a single board is a stronger form of it than comparing two digests would be.

WHAT SEPARATES THE TWO ORDERINGS, exactly. `build_board_from_lines` computes
`consensus_rank` by sorting on `(-points, player_id)` (board.py:279-289) and `vorp_rank` by
sorting on `(-vorp, player_id)` (replacement.py:190, board.py:259-260), where
`vorp = points - replacement[primary_position]` (replacement.py:185). The two sorts differ by
subtracting ONE CONSTANT PER POSITION. So:

    audible_transform - points_greedy  ==  the value of applying replacement levels

and nothing else. There is no third ingredient hiding in it.

SCARCITY DOES NOT ORDER THE BOARD, and the brief's premise that arm 2 runs "replacement and
scarcity" is refuted. `scarcity_values` is computed (board.py:264) and becomes `scarcity` and
`scarcity_rank` on each entry, but the board's order is `vorp_rank` -- `DraftBoard.entries` is
built by iterating the VORP-sorted list (board.py:94, 303). Scarcity reaches the ordering only
through `value_rank = scarcity_rank if config.value_metric == "scarcity" else vorp_rank`
(board.py:292), and BOTH leagues set `value_metric = "vorp"`
-- and so do all four league configs in the repo (espn_davis_drive:44, espn_green_hope:89,
espn_danger_zone:71, sleeper_boyfun:37). So in the configuration that actually exists, scarcity
is computed, displayed, and never orders anything. `src/audible/server/state.py:403` does not
even consult `value_metric`; it sorts on `vorp_rank` outright.

That is why Task 4's decomposition is not two arms plus a sum. "Replacement only" IS
`audible_transform`, provably and not approximately, so running it as a separate arm would be
running the same arm twice. Scarcity is run instead as a COUNTERFACTUAL ordering -- what the
board would do if the other half drove it -- which is the only way this harness can price a
term that the live configuration never consults.

(Two stale comments in production say otherwise and are worth naming, since they are what the
brief was reading. `src/audible/draft/cheatsheet.py:5` says "VORP for superflex A,
scarcity/VONA for 1-QB B"; `src/audible/draft/board.py:290-291` says "VORP for deep/scarce
formats, scarcity/VONA for shallow/flat ones". Both describe a configuration no league sets.
This session writes only inside `sim/` and so reports them rather than fixing them.)


THE ORDER IS ALL THAT CHANGES
-----------------------------
Every arm here drafts through the same rule: best available on its own ordering, subject to the
room's roster caps and the same feasibility deadline the bots and the `adp` baseline get. No
need logic, no bye term, no urgency, no shortlist. That is deliberate. B3 measured the overlay
and found every part of it null; putting it back would mix a null term into the one comparison
this session exists to make.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import ffa, projection, room

# The projection a board is built from. `walkforward` is B4's, computed here from prior
# seasons. `ffa` is B5's: the market's own vintage preseason numbers.
WALKFORWARD: str = "walkforward"
FFA_SOURCE: str = "ffa"
SOURCES: tuple[str, ...] = (WALKFORWARD, FFA_SOURCE)

# The orderings a season's boards can be read in. Each maps an arm name to the `DraftEntry`
# field its draft preference sorts on, ascending.
PROJECTED_ORDERS: dict[str, str] = {
    "points_greedy": "consensus_rank",
    "audible_transform": "vorp_rank",
    "scarcity_only": "scarcity_rank",
    "adp_board": "adp_rank",
}
# The ceiling board, read two ways. `hindsight_points` exists to separate two explanations of
# a weak `audible_transform` that otherwise look identical: a transform that does not work, and
# a transform that works on a projection too poor to carry it. Under a PERFECT projection the
# only thing left between these two orderings is still replacement level, so
# `hindsight_board - hindsight_points` is the transform's value with the input error removed.
HINDSIGHT_ORDERS: dict[str, str] = {
    "hindsight_board": "vorp_rank",
    "hindsight_points": "consensus_rank",
}

# The season-TOTAL reading of the same realised lines, kept as one arm so the harness's own
# indifference to games played stays visible. `bootstrap_weeks` replays a player's observed
# weeks to a full season, so ordering on totals demotes exactly the players it restores.
TOTAL_ORDERS: dict[str, str] = {"hindsight_total": "vorp_rank"}

# B5. A THIRD PARTY'S REPLACEMENT TRANSFORM over the same projection, read straight off FFA's
# own `points_vor` rather than computed here. It is not a field on our `DraftEntry` and cannot
# be, which is the point: `audible_transform` and `ffa_vor` are two implementations of one
# idea over one input, so their difference is the implementation and nothing else.
#
# It splits a question no earlier session could split. Both at or below `adp` says
# replacement-level thinking does not pay in this format and audible's version is fine. FFA
# ahead of `audible_transform` says the idea works and OUR VERSION IS WEAKER -- a concrete,
# fixable defect, and the most actionable outcome available.
#
# Available only when the run's projection source is `ffa`; `runner.load_config` refuses it
# otherwise rather than letting it quietly order on nothing.
FFA_ORDERS: dict[str, str] = {
    # THE LIKE-FOR-LIKE ARM. FFA's baseline DEPTH applied to OUR points under OUR rulebook, so
    # the only thing that differs from `audible_transform` is how deep the baseline sits.
    "ffa_baseline": "ffa_baseline",
    # FFA's PUBLISHED column, kept because it was asked for and reported as CONFOUNDED: FFA
    # scores 2024 and 2025 at half a point a reception and this league pays zero, so roughly
    # forty per cent of `audible_transform - ffa_vor` is the scoring table rather than the
    # transform. `sim/ffa.ffa_baseline_ranks` carries the measurement.
    "ffa_vor": "points_vor",
}

ALL_BOARD_ARMS: tuple[str, ...] = (
    *PROJECTED_ORDERS, *HINDSIGHT_ORDERS, *TOTAL_ORDERS, *FFA_ORDERS
)

# Arms whose board is built from the drafted season's own outcome. Labelled a leak everywhere,
# excluded from `assert_pre_draft`, and reported as the CEILING rather than as a result.
LEAK_ARMS: frozenset[str] = frozenset(HINDSIGHT_ORDERS) | frozenset(TOTAL_ORDERS)


@dataclass(frozen=True, slots=True)
class SeasonBoards:
    """Every B4 ordering for one season, in ROOM-BOARD INDEX SPACE, plus what built them.

    The orderings are indices into `SeasonBoard.rows`, which is the space
    `room.simulate_draft` expects a chooser to return. Converting once, here, is what stops
    the B2 defect from recurring: a chooser that returned an audible-board index while the
    room read it as its own drafted unrelated players for a whole session and the shuffle arm
    "won" by 139 points.
    """

    season: int
    orders: Mapping[str, tuple[int, ...]]
    projected_digest: str
    hindsight_digest: str
    # Which projection each arm's ordering came off. G4 is "arms 1 and 2 share byte-identical
    # projected stat lines", and this is what it reads. Today both point at one object, so the
    # equality is true by construction -- but recording it per ARM is what lets a gate FAIL if
    # someone ever builds them separately, which is the failure G4 exists for.
    arm_digest: Mapping[str, str]
    fit_seasons: tuple[int, ...]
    role_seasons: tuple[int, ...]
    matched: int
    rookies: int
    unmatched: int
    pool: int
    provenance: tuple[str, ...]
    replacement: Mapping[str, float]
    vs_adp: Mapping[str, Any]
    # Which projection built these boards, and which scoring terms it could not supply. Both
    # go in the artifact: a run that silently changed projection source or silently dropped a
    # scoring term would otherwise be indistinguishable from one that did not.
    source: str = WALKFORWARD
    unsupplied: tuple[str, ...] = ()


def _order_by(board: Any, field: str, by_index: Mapping[str, int]) -> tuple[int, ...]:
    """Room-board indices, in the draft preference the named rank field expresses.

    A `None` rank sorts last rather than raising, and that case is the common one rather than
    a defensive nicety: only the DRAFTABLE half of the universe carries an ADP, so `adp_rank`
    is None for every row of the undraftable tail -- 619 of 811 entries in 2023. They sort last
    and are then dropped by the `by_index` filter below, which is the intended path.
    """
    ranked = sorted(
        board.entries,
        key=lambda e: (getattr(e, field) is None, getattr(e, field) or 0, e.player_id),
    )
    # The undraftable tail is filtered out here for the DRAFT PREFERENCES: it exists so
    # replacement level has a real pool to find a baseline in, and it must never appear in an
    # order. The room does not know those players and a chooser returning one would be an
    # index error at best and a silent wrong pick at worst. Two other populations filter it
    # again for their own purposes -- `disagreement` compares only what the market priced, and
    # `accuracy.measure` scores only what the market priced.
    out = [by_index[e.player_id] for e in ranked if e.player_id in by_index]
    if len(out) != len(by_index):
        missing = sorted(set(by_index) - {e.player_id for e in ranked})
        raise ValueError(
            f"{field} ordering covers {len(out)} of {len(by_index)} draftable rows; "
            f"{len(missing)} missing, first few {missing[:5]}. Every arm must see the same "
            f"draft pool or the comparison is between two different universes."
        )
    return tuple(out)


def _order_by_values(
    values: Mapping[str, float], by_index: Mapping[str, int]
) -> tuple[int, ...]:
    """Room-board indices ordered by an EXTERNAL value, highest first.

    The counterpart to `_order_by` for a value that is not a field on our `DraftEntry` --
    FFA's own `points_vor`. Two things it must get right, both of them the same trap
    `_order_by` documents:

    A player the external source does not price sorts LAST rather than being dropped. Dropping
    him would hand this arm a smaller universe than every other arm, and a comparison between
    two different universes is not a comparison. The tie-break is the player id, so the order
    is total and the artifact digest reproduces.
    """
    ranked = sorted(
        by_index,
        key=lambda pid: (pid not in values, -values.get(pid, 0.0), pid),
    )
    return tuple(by_index[pid] for pid in ranked)


def build(
    season: int,
    config: Any,
    *,
    source: str = WALKFORWARD,
    deltas: dict[str, float] | None = None,
) -> SeasonBoards:
    """Build every board ordering for *season*. Expensive; the runner does it once per season.

    *source* selects the PROJECTION and nothing else. `walkforward` is B4's: built here from
    prior seasons, and the input B4 measured the transform against. `ffa` is B5's: the market's
    own vintage preseason numbers from `sim/ffa.py`. Arms 1 and 2 read two orderings off ONE
    board either way, so G4 holds under both and the arms stay comparable within a run.

    *deltas* are scoring corrections applied to the config the BOARD is built with, so the
    board is ordered under the same rulebook the outcome is scored under. See
    `ffa.with_deltas` for why that is a correction and not a preference.
    """
    from audible.draft.board import build_board_from_lines
    from audible.value.replacement import compute_vorp

    season_board = room.load_board(season)
    by_index = {f"ffc{r.rank:04d}": i for i, r in enumerate(season_board.rows)}

    config = ffa.with_deltas(config, deltas)
    if source == FFA_SOURCE:
        projected = ffa.build(season, config, adp_market=config.adp_market)
    elif source == WALKFORWARD:
        projected = projection.project(season, config)
        # G1, enforced at the one place every board arm passes through rather than only in a
        # test. The FFA path has its own pre-draft gates -- vintage, 2026, scoring -- inside
        # `ffa.build`, and they run before a line is constructed.
        projection.assert_pre_draft(projected)
    else:
        raise ValueError(
            f"unknown projection source {source!r}; expected one of "
            f"{[WALKFORWARD, FFA_SOURCE]}"
        )
    board = build_board_from_lines(config, list(projected.lines))

    hindsight_lines = projection.actual_lines(season, config)
    hindsight = build_board_from_lines(config, list(hindsight_lines.lines))
    total_lines = projection.actual_lines(season, config, per_game=False)
    total = build_board_from_lines(config, list(total_lines.lines))

    orders: dict[str, tuple[int, ...]] = {
        arm: _order_by(board, field, by_index) for arm, field in PROJECTED_ORDERS.items()
    }
    arm_digest = dict.fromkeys(PROJECTED_ORDERS, projected.digest())
    if source == FFA_SOURCE:
        values = {"ffa_baseline": projected.ffa_baseline, "ffa_vor": projected.ffa_vor}
        for arm in FFA_ORDERS:
            orders[arm] = _order_by_values(values[arm], by_index)
            # The stat-line digest is SHARED with arms 1 and 2 -- that is the claim, and G4
            # reads it -- but it cannot see a change to the value column these arms order on,
            # so the value digest is appended. A review negated every `points_vor` and watched
            # the shared digest sit still while the top five turned over.
            arm_digest[arm] = f"{projected.digest()}/{projected.value_digest()}"
    for arm, field in HINDSIGHT_ORDERS.items():
        orders[arm] = _order_by(hindsight, field, by_index)
        arm_digest[arm] = hindsight_lines.digest()
    for arm, field in TOTAL_ORDERS.items():
        orders[arm] = _order_by(total, field, by_index)
        arm_digest[arm] = total_lines.digest()

    # Reported because it is the entire difference between arms 1 and 2, and because B2 found
    # a replacement curve that was an artifact of its input (TE 48.4 against WR 147.3 off a
    # linear-in-ADP-rank points curve). Printing it is how that stays visible.
    _entries, levels = compute_vorp(
        [
            _projection_of(e)
            for e in board.entries
        ],
        config,
    )

    return SeasonBoards(
        season=season,
        orders=orders,
        projected_digest=projected.digest(),
        hindsight_digest=hindsight_lines.digest(),
        arm_digest=arm_digest,
        # The FFA projection has no fitted history and no rookie branch -- it is read off a
        # file, not walked forward -- so these read empty for that source rather than being
        # given a plausible-looking value they do not have.
        fit_seasons=getattr(projected, "fit_seasons", ()),
        role_seasons=getattr(projected, "role_seasons", ()),
        matched=projected.matched,
        rookies=getattr(projected, "rookies", 0),
        unmatched=projected.unmatched,
        pool=projected.pool,
        provenance=projected.provenance,
        replacement={pos: round(level.points, 3) for pos, level in sorted(levels.items())},
        vs_adp=disagreement(orders, season_board),
        source=source,
        unsupplied=getattr(projected, "unsupplied", ()),
    )


def _projection_of(entry: Any) -> Any:
    """A `DraftEntry` back to the `PlayerProjection` VORP consumes. Same points, same buckets."""
    from audible.models.player import PlayerProjection

    return PlayerProjection(
        player_id=entry.player_id,
        name=entry.name,
        primary_position=entry.position,
        eligible_positions=entry.eligible_positions,
        team=entry.team,
        points=entry.points,
    )


def disagreement(
    orders: Mapping[str, Sequence[int]], season_board: room.SeasonBoard
) -> dict[str, Any]:
    """G2. How far each ordering departs from the market's, over the drafted top 128.

    THE GATE THIS FEEDS IS THE GATE ON THE WHOLE SESSION. B3's finding was that the harness
    board was a monotone transform of ADP rank -- 128 of 128 exact, Pearson 1.000000 -- so
    every arm comparison measured the overlay and never the board. If these numbers come back
    the same way, this session has reproduced that defect and no arm number below it means
    anything.

    IT READS THE ORDERS THE ARMS DRAFT, WHICH IT DID NOT BEFORE, and that was a hole large
    enough to hide the very defect the gate exists to catch. The previous version took the
    board object and a HARDCODED rank field per arm -- `("audible_transform", board,
    "vorp_rank")` -- so it measured `vorp_rank` no matter what `PROJECTED_ORDERS` said the arm
    drafted. Mutation testing pointed `audible_transform` at `adp_rank`, making it a byte-exact
    copy of `adp_board`, and this function still reported 4 exact of 128 and a Pearson of
    0.839: a clean pass on a board that WAS the ADP list. Reading `orders` means the number
    describes the sequence the chooser walks and nothing else.
    """
    ranks = [row.rank for row in season_board.rows]
    out: dict[str, Any] = {}
    for arm, order in sorted(orders.items()):
        top = list(order[: room.PICKS])
        adp_ranks = [ranks[i] for i in top]
        exact = sum(1 for place, rank in enumerate(adp_ranks, start=1) if rank == place)
        apart = sum(
            1 for place, rank in enumerate(adp_ranks, start=1) if abs(rank - place) > room.TEAMS
        )
        corr, _slope = room._pearson(
            [float(r) for r in adp_ranks], [float(i) for i in range(1, len(top) + 1)]
        )
        out[arm] = {
            "exact_of_128": exact,
            "disagree_over_one_round": apart,
            "pearson": round(corr, 6),
            "top": [season_board.rows[i].name for i in top[:5]],
        }
    return out


def greedy(order: Sequence[int], season_board: room.SeasonBoard, fit: room.Fit):
    """Best available on *order*, capped like a bot, with the room's feasibility deadline.

    IDENTICAL MACHINERY TO `seat._adp_greedy`, deliberately, down to the deadline branch. The
    only thing that differs between every arm in this file and the `adp` baseline is the
    sequence handed in, which is what makes the difference between them attributable to the
    ordering and to nothing else.
    """
    rows = season_board.rows

    def choose(
        _overall: int,
        taken: Sequence[int],
        _rows: Sequence[Any],
        *,
        remaining: int = 0,
        unfilled: Sequence[str] = (),
        counts: Mapping[str, int] | None = None,
    ) -> int:
        held = dict(counts or {})
        allowed: set[str] | None = None
        if unfilled and remaining and len(unfilled) >= remaining:
            allowed = set(room.SLOT_ELIGIBILITY[unfilled[0]])
        for index in order:
            if taken[index]:
                continue
            position = rows[index].position
            if allowed is not None and position not in allowed:
                continue
            if held.get(position, 0) >= fit.caps.get(position, room.ROUNDS):
                continue
            return index
        return -1

    return choose
