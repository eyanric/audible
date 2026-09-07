"""Audible occupies a seat, and the arms that say whether to believe any of it.

TEN ARMS live here. `real` is the cockpit's own `the_call` path. `adp` is the skill baseline
and is required. `bot` is the null control and is required. `shuffle` is the leak detector and
is required. `legacy` is the page's pre-audible#61 ordering and `legacy_recommend` the MCP list
head's pre-#60 one -- two different surfaces, reported separately because the choice between
them is worth more than the comparison it feeds. Four `no_*` ablations disable one overlay term
each. `leaky-shuffle` is an injection and is never reported.

The room from B1 drafts eight bots. This puts Audible in one of the eight and lets the bots
respond to what it takes, using the cockpit's own ordering rather than a reimplementation of
it: `compute_view` builds the candidate view, `state._score_rows` composes `effective_score`,
and `urgency.the_call` names the pick. That last one is deliberate and not interchangeable --
`the_call(...)["pick"]` is what the cockpit page renders and what `recommend` returns first,
while `recommend`'s own `recommendations[0]` sorts on `grab_now` ahead of `effective_score`
and is a weaker answer.


WHAT IS BEING MEASURED, AND WHAT CANNOT BE
-------------------------------------------
THIS MEASURES ORDERING. It cannot measure projections, and no amount of work here would
change that: no vintage preseason projections exist for any of these seasons. The Sleeper API
serves today's numbers for a 2021 season, not the numbers that stood before its draft.

So the board Audible orders is built from the same FFC ADP the bots use -- see
`board_from_season`, which also records why audible's own `compute_vorp` is NOT used on it.
Value is a monotone transform of ADP rank, so the board's order IS the market's order, and
what differs between arms is audible's overlay and never the projections.

That is also why the room is a fair opponent rather than a strawman: the bots draft from the
identical board. Neither side has information the other lacks.

AND IT IS ALSO WHY THE HEADLINE NUMBER IS NOT WHAT IT LOOKS LIKE. The bots reach -- they draw
`rank + mu[position] + N(0, sigma)`, by fitted amounts, the way real drafters do. The seat
draws nothing, so it collects every player the room reaches past: measured over 60 drafts,
the seat obtains mean ADP rank 62.3 against the opponents' 69.1. ANY noiseless seat wins that
room by well over a hundred points, which is why the `adp` arm exists and why it is required.


THE SHUFFLE ARM IS NOT OPTIONAL
--------------------------------
Five prior validation attempts have failed, so a sixth that suddenly succeeds is assumed
leaky until the shuffle says otherwise. The shuffle arm is Audible's board randomised --
every player's value permuted, everything else identical, same room, same bootstrap draws,
same seat, same seed.

WHAT "AT CHANCE" MEANS HERE, precisely, because the phrase is easy to wave at: a shuffled
board must show NO ADVANTAGE over the bots. It is not a claim that it ties them -- a seat
drafting a scrambled board should be somewhat WORSE than eight ADP bots, and usually is.
The failure it detects is the opposite one: if the harness leaks outcome information into the
draft, even a scrambled board wins, because the leak and not the ordering is doing the work.

AND THE ASSUMED SIGNATURE TURNED OUT TO BE WRONG, which is worth more than the gate it
replaced. A real outcome leak was built to test it -- a seat re-ranking its own shortlist by
what each player went on to score -- and `real - shuffle` WIDENED, from +92 to +428, because
the leak helps whichever arm has the better shortlist. Every gate passed while the real arm
sat at +479.8. So the detectable signature is SIZE, not collapse: see
`runner.leak_ceiling_failures`, which is G6d, and `test_i7_an_outcome_informed_seat_is_caught`,
which fires it.


PAIRING
-------
Every arm sees the same rooms, the same bootstrap draws and the same seat. Only the arm
differs. Unpaired comparison spends most of its power on variance that cancels -- the same
room and the same weekly draws move every arm together, and differencing removes them.
`run_arm` therefore takes the seed and derives every stream from it, so arm A and arm B at
seed 7 face the identical opponent field.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import room, weekly

# Audible's seat. Green Hope's live seat is 6 of 8 (leagues/espn_green_hope.toml), and 6012's
# is 8 of 8. Six is used because it is the seat that matters on Tuesday, and because a
# mid-board seat has both a wheel and a full set of neighbours on either side.
DEFAULT_SEAT: int = 6

# Points handed to the top of the board, and to the bottom. The transform is monotone in ADP
# rank and nothing else, so it carries no information the bots do not also have. The SCALE is
# arbitrary and cancels, because every arm shares it.
TOP_POINTS: float = 340.0
BOTTOM_POINTS: float = 40.0


def board_from_season(
    season_board: room.SeasonBoard,
    config: Any,  # noqa: ARG001 -- kept so a config-derived board can be added without a
    #                              signature change at every call site; unused today because
    #                              value is a monotone transform of ADP rank and nothing else.
    *,
    shuffle: random.Random | None = None,
) -> Any:
    """An `audible.draft.board.DraftBoard` over the season's FFC rows.

    THE BOARD'S VALUE ORDER IS THE MARKET'S ORDER, and that is a deliberate refusal to invent
    projections. Value is linear in ADP rank -- rank 1 gets TOP_POINTS, the last row gets
    BOTTOM_POINTS -- and `vorp` carries the same number, so the board ranks players exactly as
    the market did. What the arms then differ on is audible's OVERLAY: need, marginal start
    factor, bye conflict, urgency, the whole of `effective_score` and The Call's sort. That is
    what B2 can measure and it is all B2 can measure.

    WHY `compute_vorp` IS NOT USED HERE, since not using the real value engine deserves an
    argument. It was, in the first version, over exactly this linear points curve. Measured,
    the result was a positional artifact and not a small one:

        replacement level from a linear-in-ADP-rank curve, 2024:
          TE 48.4   DEF 0.0   K 61.8   WR 147.3   RB 155.6   QB 224.4
        top three by VORP: Travis Kelce, Sam LaPorta, Mark Andrews

    Tight ends are sparse and spread deep in ADP, so a linear curve puts TE replacement at
    48 while WR sits at 147, and three tight ends rank above Christian McCaffrey. The seat then
    drafted FIVE of them. None of that is audible's doing -- it belongs entirely to the shape
    of the curve fed to a replacement engine that was built to consume real projections, and
    there are none for any of these seasons. Manufacturing one and then measuring the ordering
    on top of it would be measuring the manufacture.

    So replacement is uniform here and the board is the market. `compute_vorp` stays exercised
    where it has real projections, which is production.

    *shuffle*, when given, permutes which value goes to which player. Positions, byes, ADP and
    eligibility are untouched; only the value ordering moves. Keeping the arm to one argument
    is what makes it credible that the two differ in nothing else.
    """
    from audible.draft.board import DraftBoard, DraftEntry

    rows = season_board.rows
    n = len(rows)
    span = TOP_POINTS - BOTTOM_POINTS
    points = [TOP_POINTS - span * (r.rank - 1) / max(1, n - 1) for r in rows]
    if shuffle is not None:
        shuffle.shuffle(points)

    order = sorted(range(n), key=lambda i: (-points[i], rows[i].rank))
    value_rank = [0] * n
    for place, i in enumerate(order, start=1):
        value_rank[i] = place

    entries = [
        DraftEntry(
            player_id=f"ffc{r.rank:04d}",
            name=r.name,
            position=r.position,
            eligible_positions=frozenset({r.position}),
            team=r.team or "XX",
            model="consensus",
            points=pts,
            modeled_xfp=0.0,
            carried=0.0,
            consensus=pts,
            vorp=pts,
            vorp_rank=value_rank[i],
            consensus_rank=value_rank[i],
            opp_rank=value_rank[i],
            deviation=False,
            scarcity=pts,
            scarcity_rank=value_rank[i],
            adp=r.adp,
            adp_rank=r.rank,
            value=0,
            flags=(),
        )
        for i, (r, pts) in enumerate(zip(rows, points, strict=True))
    ]
    return DraftBoard(
        league_key=f"sim_{season_board.season}",
        entries=sorted(entries, key=lambda e: e.vorp_rank),
    )


def reset_state_caches(byes: dict[str, int]) -> None:
    """Clear the three unkeyed process globals in `server/state.py` and seed the bye one.

    THEY ARE KEYED BY NOTHING. `_gap_cache`, `_rank_cache` and `_bye_cache` are bare module
    globals, so the first league or season through the process serves every later one --
    `bye_weeks(season)` ignores its own `season` argument on the second call. A sweep that
    walks 2021 to 2025 in one process gets 2021's byes for all five, silently, and every bye
    collision and every `marginal_bye_cost` downstream is then wrong.

    Seeding `_bye_cache` also keeps the run OFFLINE: `bye_weeks` would otherwise reach for
    `schedules_<season>`, which is pinned for 2026 and no earlier season.
    """
    from audible.server import state as state_mod

    state_mod._gap_cache = {}
    state_mod._rank_cache = {}
    state_mod._bye_cache = dict(byes)


@dataclass(slots=True)
class AudibleSeat:
    """One seat driven by the cockpit's own ordering."""

    service: Any
    board: Any
    byes: dict[str, int]
    # player_id -> index into the ROOM's board, which is the index `simulate_draft` speaks.
    # These are two orderings of the same players -- the room walks `SeasonBoard.rows` in ADP
    # order, audible's board is sorted by `vorp_rank` -- and handing back the wrong one was a
    # real defect: the seat returned an audible index, the room read it as its own, and every
    # pick landed on an unrelated player while the mirrored id said something else again. It
    # looked like a working harness. The shuffle arm was "winning" by 139 points.
    by_index: dict[str, int]
    # Which ordering this seat runs. "real" is the cockpit's own `the_call`; "legacy" is
    # `the_call`'s pre-audible#61 form; "legacy_recommend" is the MCP list head's pre-#60 sort;
    # the four `no_*` names disable one term each.
    mode: str = "real"
    calls: int = 0
    # Picks that came from the feasibility deadline rather than from the ordering. Reported,
    # because it is the size of a real finding -- see `choose`.
    deadline_picks: int = 0

    def choose(
        self,
        overall: int,
        taken: Sequence[int],
        rows: Sequence[Any],
        *,
        remaining: int = 0,
        unfilled: Sequence[str] = (),
        counts: Mapping[str, int] | None = None,
    ) -> int:
        """The board index Audible would take. Returns -1 when it has no legal answer.

        THE DEADLINE IS THE HARNESS'S, NOT AUDIBLE'S, and the distinction matters.

        Audible's ordering, drafting sixteen picks unassisted, finishes without a kicker in 10.0%
        of drafts, without a defence in 23.3%, and short of at least one of the two in 26.7%.
        Re-measured at HEAD over 60 drafts (five seasons, twelve seeds) with the seat's `unfilled`
        argument forced empty and the room's deadline left on; at that sample size each figure is
        +/- several points and it is the ORDER of magnitude that matters. (Two earlier versions of
        this docstring gave 88% and then 6.0/23.7/25.7 with no conditions attached; neither
        reproduced, which is why the conditions are now stated beside the numbers.) That is not a
        bug in The Call: `the_call` ranks on `effective_score`, a kicker's value sits at ADP rank
        138 or worse, and it will rarely surface above a startable receiver. It is also not how
        the tool is used -- the cockpit is open on a desk next to somebody who can see an empty
        D/ST slot in round fifteen and does something about it.

        So the harness applies the SAME feasibility deadline the bots get: with as many picks
        left as unfilled starting slots, fill the most specific one, using audible's own
        ordering restricted to that slot. Giving the bots an endgame rule and denying it to
        the seat would be a strawman in the other direction.

        `deadline_picks` counts how often it fired, and the artifact reports it, so the
        finding stays visible instead of being absorbed into a number that looks fine.
        """
        from audible.draft import urgency
        from audible.server import state as state_mod

        view = self.service.view()
        if view is None:
            return -1
        pool = state_mod._served_pool(self.service, view)
        served = [
            state_mod._player(c, gaps={}, byes=self.byes, usage=self.service.usage)
            for c in pool
        ]
        state_mod._score_rows(self.service, view, served, self.byes)

        # THE ABLATIONS. `_score_rows` has already composed `effective_score` from
        # `max(0, vorp) * marginal_start_factor - bye_conflict_penalty`; disabling a term means
        # neutralising it and recomposing from the same three parts, which is exactly what
        # `ordering.effective_score` does. Recomposing here rather than monkeypatching
        # `ordering` keeps the ablation inside sim/ and keeps production code untouched.
        if self.mode in ("no_need", "no_bye"):
            for row in served:
                base = max(0.0, float(row.get("vorp") or 0.0))
                factor = 1.0 if self.mode == "no_need" else float(
                    row.get("marginal_start_factor") or 1.0
                )
                penalty = 0.0 if self.mode == "no_bye" else float(
                    row.get("bye_conflict_penalty") or 0.0
                )
                row["marginal_start_factor"] = round(factor, 4)
                row["bye_conflict_penalty"] = round(penalty, 3)
                row["effective_score"] = round(base * factor - penalty, 3)

        # The row rebuild is `state._the_call`'s, field for field. It has to be: those rows
        # are built by hand and anything not named here is silently dropped, and the field
        # that got dropped last time was `effective_score` -- The Call then fell back to raw
        # `vorp_rank` and named a player who could not start. That was defect G-CALL.
        rows_for_call = [
            {
                "id": p["id"], "name": p["name"], "position": p["position"],
                "vorp_rank": p["vorp_rank"], "adp": p.get("adp"),
                "platform_rank": p.get("espn_rank"),
                "effective_score": p.get("effective_score"),
                "marginal_start_factor": p.get("marginal_start_factor"),
                "bye_conflict_penalty": p.get("bye_conflict_penalty"),
                "bye_week": p.get("bye"),
            }
            for p in served
        ]
        taken_ids = self.service.session.taken_ids()
        available = [e for e in self.board.entries if e.player_id not in taken_ids]
        self.calls += 1

        legacy_pick: int | None = None
        if self.mode == "legacy_recommend":
            # `recommend`'s pre-audible#60 sort, verbatim from `mcp.py` at 6bdb2e7^:
            #     key=lambda p: (not p["grab_now"], p["vorp_rank"], not p["fills_need"])
            # The third key is DEAD and that is the point: `vorp_rank` is a unique, gapless
            # integer, so a key placed after it is never compared. Need was computed,
            # published, and then discarded at the moment of ordering. (In this harness the
            # rank comes from `board_from_season` below, tie-broken on ADP rank; in production
            # from `board.py:260` over a `(-vorp, player_id)` total order. Unique either way.)
            #
            # This is the MCP list head, NOT the page's answer. It is reported beside
            # `legacy` rather than as it, because `real` runs `the_call` and comparing a
            # `the_call` arm against a `recommend` arm is comparing two surfaces. That
            # conflation is what this arm exists to undo: `legacy` used to BE this sort, so
            # `real - legacy` was a surface comparison wearing an ordering comparison's name,
            # and separating them inverted its sign. The size of the surface gap is in the
            # artifact as `surface_gap` -- null under the prior lineup, resolvably positive
            # under the oracle one, which is itself a warning about reading either alone.
            #
            # The `forced` need-filter that `recommend` applies at slack <= 0 is omitted: it
            # reads a clock block this harness does not build. It fires only once the clock
            # slack is exhausted, which is the same corner the harness deadline covers, so
            # the omission is not expected to matter -- but that is an argument, not a
            # measurement, and it is the one respect in which this arm is not verbatim.
            ranked = sorted(
                served,
                key=lambda p: (
                    not p.get("grab_now"), p["vorp_rank"], not p.get("fills_need")
                ),
            )
            legacy_pick = next(
                (
                    idx
                    for row in ranked
                    if (idx := self.by_index.get(str(row["id"]), -1)) >= 0
                    and not taken[idx]
                ),
                -1,
            )

        call: dict[str, Any] = {}
        if self.mode == "legacy":
            # THE PAGE'S PRE-audible#61 ANSWER, which is the like-for-like comparison against
            # `real`. Reconstructed from `urgency.py` at d3c3a24^: the shortlist is a raw
            # board-rank slice `candidates[:TOP_N]` rather than an `effective_score` sort, and
            # the final key is `(-need, urgency, vorp_rank)` with no `effective` term.
            #
            # `effective_score` is dropped from the rows rather than the sort being rewritten,
            # because `the_call` falls back to 0.0 for a missing key and then BOTH its sorts
            # collapse to `vorp_rank` -- which is exactly the pre-#61 behaviour, and is the
            # seam `state._the_call`'s own comment identifies as how the field went missing in
            # the first place.
            legacy_rows = [
                {k: v for k, v in row.items() if k != "effective_score"}
                for row in rows_for_call[: urgency.TOP_N]
            ]
            call = urgency.the_call(
                legacy_rows,
                next_pick=view.my_next_pick,
                needs=urgency.roster_needs(
                    state_mod._roster_slots(view), self.service.config.slot_eligibility
                ),
                available_entries=available,
            )
        elif self.mode != "legacy_recommend":
            # `no_urgency`: `the_call` never reads `grab_now` at all -- that key belongs to
            # `recommend`. Its only urgency input is `survives_by(adp, next_pick)`, which
            # drives both the will-last skip and `_urgency_tier`. Handing it `next_pick=None`
            # makes `survives_by` return None for every row, so nothing is skipped as
            # likely-to-last and the tier is the constant 1: the term is neutralised without
            # touching the function.
            next_pick = None if self.mode == "no_urgency" else view.my_next_pick
            original_top_n = urgency.TOP_N
            if self.mode == "no_slice":
                urgency.TOP_N = NO_SLICE_TOP_N
            try:
                call = urgency.the_call(
                    rows_for_call,
                    next_pick=next_pick,
                    needs=urgency.roster_needs(
                        state_mod._roster_slots(view), self.service.config.slot_eligibility
                    ),
                    available_entries=available,
                )
            finally:
                urgency.TOP_N = original_top_n

        if unfilled and remaining and len(unfilled) >= remaining:
            allowed = set(room.SLOT_ELIGIBILITY[unfilled[0]])
            forced = [
                row for row in rows_for_call
                if row["position"] in allowed
                and (idx := self.by_index.get(str(row["id"]), -1)) >= 0
                and not taken[idx]
            ]
            if not forced:
                # The served pool is a top-60 slice plus per-position depth, so a kicker can
                # be absent from it entirely. Fall back to the whole available board, still
                # in audible's own value order.
                forced_entries = [
                    e for e in available
                    if e.position in allowed
                    and (idx := self.by_index.get(e.player_id, -1)) >= 0
                    and not taken[idx]
                ]
                if forced_entries:
                    self.deadline_picks += 1
                    return self.by_index[forced_entries[0].player_id]
            else:
                self.deadline_picks += 1
                best = min(
                    forced, key=lambda r: -float(r.get("effective_score") or 0.0)
                )
                return self.by_index[str(best["id"])]

        if legacy_pick is not None:
            return legacy_pick

        pick = call.get("pick") or {}
        pid = pick.get("id")
        if pid is None:
            return -1
        index = self.by_index.get(str(pid), -1)
        return -1 if index < 0 or taken[index] else index


def build_seat(
    season_board: room.SeasonBoard,
    config: Any,
    byes: dict[str, int],
    state_dir: Path,
    *,
    seat: int = DEFAULT_SEAT,
    shuffle: random.Random | None = None,
    mode: str = "real",
) -> AudibleSeat:
    """A `CockpitService` holding the season board, with no network and no poll thread.

    `warm_board()` is never called -- that is the function that fetches. The board and the
    usage table are assigned directly, which is the pattern `sim/harness.py` established.
    """
    import time

    from audible.draft.service import CockpitService
    from audible.draft.usage import UsageTable

    reset_state_caches(byes)
    board = board_from_season(season_board, config, shuffle=shuffle)
    service = CockpitService(config, state_dir=state_dir, slot_override=seat)
    service.board = board
    service.usage = UsageTable(bye_by_team=dict(byes))
    service.session.draft_id = f"sim{season_board.season}"
    service.session.draft_status = "drafting"
    service.session.slot = seat
    service.session.slot_source = "override"
    service.session.rounds = config.draft_rounds
    service.session.picks = []
    service.health.last_success = time.time()
    return AudibleSeat(
        service=service,
        board=board,
        byes=dict(byes),
        by_index={
            f"ffc{r.rank:04d}": i for i, r in enumerate(season_board.rows)
        },
        mode=mode,
    )


# The ablations, each identical to `real` except that one named term is disabled. B3 exists to
# answer "which of these mechanisms contributes anything measurable", and an ablation whose
# result is indistinguishable from `real` is a fact about the tool worth knowing regardless of
# what any sweep would say.
ABLATIONS: frozenset[str] = frozenset({"no_need", "no_bye", "no_urgency", "no_slice"})

ARMS: frozenset[str] = (
    frozenset(
        {"real", "shuffle", "bot", "adp", "legacy", "legacy_recommend", "leaky-shuffle"}
    )
    | ABLATIONS
)

# How far past the ADP baseline an honest ordering could plausibly get, in points-for over a
# bootstrapped season. The board's values are a MONOTONE TRANSFORM OF ADP RANK, so there is no
# better ordering of it to find -- audible's whole contribution is its overlay, and the overlay
# is worth tens of points, not hundreds. Anything past this has information the board does not
# contain. Measured: an oracle seat that picks whoever actually scored most that season clears
# the baseline by roughly +330; the honest arm sits at -27 to -35.
#
# It is a CEILING, not a target. Nothing is tuned against it and no honest run approaches it:
# the real arm's distance from the ADP baseline has read between -16 and +13 across every
# lineup policy measured, against a ceiling of 150.
LEAK_CEILING: float = 150.0

# Arms that must all be present for the report to mean anything. `real` is the thing under
# test, `shuffle` is the leak detector, `bot` is the null that says the machinery is sound,
# and `adp` is the skill baseline that says whether beating the bots is an achievement.
REQUIRED_ARMS: frozenset[str] = frozenset({"real", "shuffle", "bot", "adp"})

# How far the `no_slice` ablation opens the shortlist. `urgency.TOP_N` is 12; this is larger
# than any served pool this harness produces -- measured 59 to 145 rows, mean 117, over 2,835
# calls -- so the cap is removed rather than widened. (`state.py`'s own "~200 rows" describes
# the production poll path, not this one.) Restored in a `finally`: it is a module global on
# production code.
NO_SLICE_TOP_N: int = 10_000


def _adp_greedy(season_board: room.SeasonBoard, fit: room.Fit):
    """Best available by ADP rank, capped like a bot, deadline like the seat. No audible.

    Deliberately the dumbest thing that is not obviously stupid, because that is what a
    baseline is for. It carries no need logic beyond the deadline, no bye term, no surplus
    discount and no survival estimate.
    """
    rows = season_board.rows

    def choose(
        overall: int,
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
        for i, row in enumerate(rows):
            if taken[i]:
                continue
            if allowed is not None and row.position not in allowed:
                continue
            if held.get(row.position, 0) >= fit.caps.get(row.position, room.ROUNDS):
                continue
            return i
        return -1

    return choose


@dataclass(frozen=True, slots=True)
class ArmResult:
    arm: str
    season: int
    seed: int
    seat: int
    points_for: float
    opponent_points: tuple[float, ...]
    unresolved: int
    picks: tuple[Any, ...]
    calls: int
    deadline_picks: int
    # The two upper bounds, kept so the harness's own uncertainty about what a manager could
    # have known is visible beside the primary rather than argued about.
    points_for_season_mean: float = 0.0
    season_mean_opponent_points: tuple[float, ...] = ()
    points_for_realised: float = 0.0
    realised_opponent_points: tuple[float, ...] = ()
    # Points by starting slot, seat only, under the PRIMARY (ex-ante) lineup. Reported for
    # every arm in every artifact -- the tight-end result hid for a whole session because
    # nothing broke the advantage down by slot.
    slot_points: dict[str, float] = field(default_factory=dict)

    @property
    def advantage(self) -> float:
        """Points-for minus the mean opponent seat. The paired quantity every arm reports."""
        return self.points_for - (
            sum(self.opponent_points) / len(self.opponent_points)
            if self.opponent_points
            else 0.0
        )

    @property
    def advantage_season_mean(self) -> float:
        """Under the season-mean lineup: an ORACLE projection. An upper bound, not ex-ante."""
        return self.points_for_season_mean - (
            sum(self.season_mean_opponent_points) / len(self.season_mean_opponent_points)
            if self.season_mean_opponent_points
            else 0.0
        )

    @property
    def advantage_realised(self) -> float:
        """Under the realised-point lineup: hindsight. The far upper bound."""
        return self.points_for_realised - (
            sum(self.realised_opponent_points) / len(self.realised_opponent_points)
            if self.realised_opponent_points
            else 0.0
        )


def run_arm(
    arm: str,
    season: int,
    seed: int,
    *,
    season_board: room.SeasonBoard,
    fit: room.Fit,
    week_table: weekly.SeasonWeekly,
    config: Any,
    state_dir: Path,
    seat: int = DEFAULT_SEAT,
    prior: Mapping[tuple[str, int], float] | None = None,
) -> ArmResult:
    """One draft with Audible in *seat*, then one bootstrapped season scored on it.

    PAIRING, stated precisely because the obvious claim is false and three docstrings used to
    make it. Every stream is derived from *seed* alone, so two arms at seed 7 share the room's
    latent draws and the same opponent model. They do NOT face the identical realised opponent
    field: the room is reactive, so a different seat pick changes what is on the board when
    the next opponent chooses. Measured over 60 (season, seed) pairs, `no_need` differs from
    `real` on 60 of 60, moving 15 to 62 of the 112 opponent picks; `no_bye` differs on 56 of
    60, moving 0 to 67.

    Nor are the weekly draws identical across arms. `bootstrap_weeks` consumes the stream in
    roster order and takes zero draws for a player with no weeks, so a roster that differs at
    pick 3 shifts every draw after it.

    None of that biases anything -- the draws are i.i.d. and the intervals cluster on season
    means -- but it costs the variance reduction a truly paired design would give, which the
    already-wide clustered intervals cannot spare. It is stated here because "identical" is
    the kind of claim a reader would reasonably rely on.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {sorted(ARMS)}")

    if arm == "adp":
        # THE SKILL BASELINE, and the arm that decides whether any of this is evidence.
        # Ten lines, no audible in it at all: take the best un-taken ADP rank, respect the
        # same roster caps the bots have, honour the same feasibility deadline the seat gets.
        # If audible cannot beat this it has not been shown to do anything, however far ahead
        # of the bots it lands -- and it does not. See the module docstring.
        picks = room.simulate_draft(
            season_board, fit, seed,
            chooser=_adp_greedy(season_board, fit),
            chooser_seat=seat,
        )
        return _score_draft(
            arm, season, seed, seat, picks, season_board, week_table, 16, 0, prior
        )

    if arm == "bot":
        # THE NULL CONTROL. Seat 6 played by the room's own bot logic -- no audible board, no
        # the_call, no overlay. By symmetry its advantage over the other seven must be zero,
        # and measuring that it IS zero is what says the measurement machinery is sound before
        # any arm's number is believed. It is also the baseline the other two are read against:
        # shuffle minus bot is what audible's structure is worth, real minus shuffle is what
        # its value ordering is worth.
        picks = room.simulate_draft(season_board, fit, seed)
        return _score_draft(
            arm, season, seed, seat, picks, season_board, week_table, 0, 0, prior
        )

    # `leaky-shuffle` is the injection: a shuffle arm with the shuffle removed, so it reads
    # the real board. `real - shuffle` then collapses to exactly zero, which is the signature
    # G6b exists to catch. It is never a reported arm.
    shuffle_rng = random.Random(seed) if arm == "shuffle" else None
    # `real`, `shuffle` and `leaky-shuffle` all run the cockpit's own ordering; the board is
    # what differs. `legacy` and the four ablations differ in the ORDERING and share the board.
    mode = arm if arm in ABLATIONS or arm.startswith("legacy") else "real"
    holder = build_seat(
        season_board, config, week_table.byes, state_dir,
        seat=seat, shuffle=shuffle_rng, mode=mode,
    )
    from audible.draft.live import Pick

    rows = season_board.rows

    def chooser(
        overall: int,
        taken: Sequence[int],
        rows_: Sequence[Any],
        *,
        remaining: int = 0,
        unfilled: Sequence[str] = (),
        counts: Mapping[str, int] | None = None,
    ) -> int:
        return holder.choose(
            overall, taken, rows_,
            remaining=remaining, unfilled=unfilled, counts=counts,
        )

    def observe(pick: room.SimPick, board_index: int) -> None:
        """Mirror every pick into the cockpit, and invalidate the memoised view.

        `session.picks` is a plain list and mutating it does NOT bump `_state_version`, so
        `service.view()` would keep returning the pre-draft view forever and the seat would
        recommend the same player at every pick. `_invalidate()` is the only thing that
        settles it.
        """
        pid = (
            f"ffc{rows[board_index].rank:04d}"
            if board_index >= 0
            else f"offboard{pick.overall}"
        )  # an off-board pick has no board row, so it is mirrored under its own id
        holder.service.session.picks.append(
            Pick(
                pick_no=pick.overall,
                round=pick.round,
                draft_slot=pick.seat,
                player_id=pid,
            )
        )
        # `_invalidate`'s own docstring says callers must hold the lock. This harness is
        # single-threaded and never starts the poll thread, so there is no other holder; the
        # contract is noted rather than silently ignored.
        holder.service._invalidate()

    picks = room.simulate_draft(
        season_board,
        fit,
        seed,
        chooser=chooser,
        chooser_seat=seat,
        observer=observe,
    )

    return _score_draft(
        arm, season, seed, seat, picks, season_board, week_table,
        holder.calls, holder.deadline_picks, prior,
    )


def _score_draft(
    arm: str,
    season: int,
    seed: int,
    seat: int,
    picks: Sequence[room.SimPick],
    season_board: room.SeasonBoard,
    week_table: weekly.SeasonWeekly,
    calls: int,
    deadline_picks: int,
    prior: Mapping[tuple[str, int], float] | None = None,
) -> ArmResult:
    """Score a completed draft. Every seat gets its own bootstrap stream, keyed off the seed.

    The streams are `seed * 1_000_003 + seat`, so arm A and arm B at the same seed give seat 6
    the identical weekly draws and the difference between them is the draft and nothing else.
    """
    rosters: dict[int, list[room.SimPick]] = {}
    for p in picks:
        rosters.setdefault(p.seat, []).append(p)

    ranks = positional_ranks(season_board)

    def score(who: Sequence[room.SimPick], stream: int):
        """All three lineup policies off ONE bootstrap draw per seat.

        `random.Random` is re-seeded identically for each policy, and `bootstrap_weeks`
        consumes exactly 18 draws per player regardless of content, so the three cannot
        desynchronise. That is what makes them three readings of one experiment rather than
        three experiments.
        """
        roster, missing = weekly.resolve_roster(who, season_board, week_table)
        table = weekly.prior_points(prior or {}, roster, ranks)
        primary, slots = weekly.points_for(
            random.Random(stream), week_table, roster, lineup="prior", prior=table
        )
        oracle, _ = weekly.points_for(
            random.Random(stream), week_table, roster, lineup="season-mean"
        )
        hindsight, _ = weekly.points_for(
            random.Random(stream), week_table, roster, lineup="realised"
        )
        return primary, oracle, hindsight, slots, missing

    mine_points, mine_oracle, mine_realised, slot_points, unresolved = score(
        rosters[seat], seed * 1_000_003 + seat
    )
    opponents: list[float] = []
    opponents_oracle: list[float] = []
    opponents_realised: list[float] = []
    for other in sorted(rosters):
        if other == seat:
            continue
        primary, oracle, hindsight, _slots, _missing = score(
            rosters[other], seed * 1_000_003 + other
        )
        opponents.append(primary)
        opponents_oracle.append(oracle)
        opponents_realised.append(hindsight)

    return ArmResult(
        arm=arm, season=season, seed=seed, seat=seat,
        points_for=mine_points, opponent_points=tuple(opponents),
        unresolved=unresolved, picks=tuple(picks), calls=calls,
        deadline_picks=deadline_picks,
        points_for_season_mean=mine_oracle,
        season_mean_opponent_points=tuple(opponents_oracle),
        points_for_realised=mine_realised,
        realised_opponent_points=tuple(opponents_realised),
        slot_points=slot_points,
    )


def positional_ranks(season_board: room.SeasonBoard) -> dict[str, int]:
    """gsis-less key -> its rank WITHIN its position on the board. The prior's key.

    Keyed by the same `ffc####` id the rest of the harness speaks, then translated to gsis by
    the caller through `resolve_roster`'s output order. Positional rather than overall rank
    because that is the slot a manager is actually filling: RB7 means something across
    seasons, overall pick 43 does not.
    """
    seen: dict[str, int] = {}
    out: dict[str, int] = {}
    for row in season_board.rows:
        seen[row.position] = seen.get(row.position, 0) + 1
        out[f"ffc{row.rank:04d}"] = seen[row.position]
    return out


# Two-sided 95% t quantiles, indexed by degrees of freedom. Only small df matter here: the
# clusters are SEASONS and there are five of them, so df is 4 and 2.776 is a long way from
# the 1.96 a normal approximation would use.
_T95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042,
}


def _t95(df: int) -> float:
    if df <= 0:
        return float("inf")
    for key in sorted(_T95):
        if df <= key:
            return _T95[key]
    return 1.96


def mean_and_interval(
    values: Sequence[float], clusters: Sequence[Any] | None = None
) -> tuple[float, float, float]:
    """(mean, lo, hi) at 95%, CLUSTERED ON SEASON when the clusters are given.

    THE UNCLUSTERED VERSION WAS WRONG AND IT WAS WRONG IN THE DIRECTION THAT FLATTERS. A run
    of 300 units is five seasons by sixty seeds, and within a season every seed shares one
    board, one ADP vintage and one set of actuals. Sixty draws from 2023 are sixty views of
    ONE market, so dividing by the square root of 300 counts each season sixty times.

    Degrees of freedom are however many season-clusters the caller passes, not always four:
    the walk-forward splits call this at 2 df and 1 df, where the t quantile is 4.303 and
    12.706 and the interval is too wide to resolve anything.

    THERE IS NO SINGLE RATIO BETWEEN THE TWO, and an earlier version of this docstring quoted
    one. It said the flat interval is "2.5 to 2.9 times too narrow", which no arm on the B3
    run reaches. Measured over its 3,000 main units, clustered width against flat width:

        adp 1.17x   bot 1.26x   legacy 1.90x   legacy_recommend 1.33x
        no_bye 1.82x   no_need 1.60x   no_slice 2.57x   no_urgency 2.53x
        real 2.05x   shuffle 1.51x

    The spread is the point. The ratio is a function of how much of an arm's variance sits
    BETWEEN seasons rather than between seeds, so an arm whose behaviour barely changes with
    the vintage (`adp`) is barely widened and one that swings with it (`no_slice`) is widened
    two and a half times. Any fixed multiplier is wrong for every arm.

    `_compare` writes `flat_lo`/`flat_hi` beside `lo`/`hi` in every comparison the artifact
    reports, so this can be re-derived rather than believed, and so a gate can read both.

    So the interval is over SEASON MEANS with a t quantile on (number of seasons - 1) degrees
    of freedom. It is much wider and it is the honest width: the thing that limits this
    measurement is five markets, not three hundred seeds, and no number of seeds fixes that.
    """
    import statistics as st

    if not values:
        return 0.0, 0.0, 0.0
    mean = st.mean(values)
    if clusters is None:
        if len(values) == 1:
            return mean, mean, mean
        sem = st.stdev(values) / len(values) ** 0.5
        return mean, mean - 1.96 * sem, mean + 1.96 * sem

    grouped: dict[Any, list[float]] = {}
    for value, key in zip(values, clusters, strict=True):
        grouped.setdefault(key, []).append(value)
    means = [st.mean(v) for v in grouped.values()]
    if len(means) < 2:
        # One cluster is one market. There is no interval to give and pretending otherwise by
        # falling back to a flat SEM over seeds is exactly the error this function exists to
        # stop, so it says "unresolvable" and every consumer has to handle that.
        return mean, float("-inf"), float("inf")
    grand = st.mean(means)
    sem = st.stdev(means) / len(means) ** 0.5
    half = _t95(len(means) - 1) * sem
    return grand, grand - half, grand + half


def shuffle_verdict(results: Sequence[ArmResult]) -> dict[str, Any]:
    """Is the shuffle arm at chance? One-sided: it must not be significantly POSITIVE.

    See the module docstring for why the test is one-sided. A shuffled board being WORSE than
    the opponent field is the expected, healthy outcome and is not a failure.
    """
    advantages = [r.advantage for r in results if r.arm == "shuffle"]
    mean, lo, hi = mean_and_interval(advantages)
    return {
        "n": len(advantages),
        "advantage": round(mean, 2),
        "lo": round(lo, 2),
        "hi": round(hi, 2),
        "at_chance": bool(lo <= 0.0),
        "reading": (
            "shuffle shows no advantage over the field"
            if lo <= 0.0
            else "SHUFFLE IS WINNING -- assume a leak until this is explained"
        ),
    }
