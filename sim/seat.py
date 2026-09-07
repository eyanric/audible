"""TASK B2/5 -- Audible occupies a seat, and the shuffle arm that says whether to believe it.

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
`board_from_season`. Points come from ADP rank through a monotone transform, and VORP comes
from `audible.value.replacement.compute_vorp` over those points, which is the real value
engine and the real config-derived replacement levels. What differs between arms is the
ORDER, never the projections, because both arms have the same ones.

That is also why the room is a fair opponent rather than a strawman: the bots draft from the
identical board. Neither side has information the other lacks.


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

So the gate is one-sided: the shuffle arm's paired advantage over the opponent field must not
be significantly POSITIVE. `shuffle_verdict` returns that number with an interval, and
`test_g_runner.py` fires an injection that points the shuffle arm at the real board to prove
the detector can go red.


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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import room, weekly

# Audible's seat. Green Hope's live seat is 6 of 8 (leagues/espn_green_hope.toml), and 6012's
# is 8 of 8. Six is used because it is the seat that matters on Tuesday, and because a
# mid-board seat has both a wheel and a full set of neighbours on either side.
DEFAULT_SEAT: int = 6

# Points handed to the top of the board, and to the bottom. The transform is monotone in ADP
# rank and nothing else, so it carries no information the bots do not also have. The span is
# chosen to put replacement level somewhere sane for `compute_vorp`; the SCALE is arbitrary
# and cancels, because every arm shares it.
TOP_POINTS: float = 340.0
BOTTOM_POINTS: float = 40.0


def board_from_season(
    season_board: room.SeasonBoard,
    config: Any,
    *,
    shuffle: random.Random | None = None,
) -> Any:
    """An `audible.draft.board.DraftBoard` over the season's FFC rows.

    Points are a linear function of ADP rank -- rank 1 gets TOP_POINTS, the last row gets
    BOTTOM_POINTS -- and VORP comes from the real `compute_vorp`, so replacement level is
    derived from the league config exactly as it is in production.

    *shuffle*, when given, permutes which POINTS go to which player before VORP is computed.
    Positions, byes, ADP and eligibility are untouched; only the value ordering moves. That is
    the whole of the shuffle arm, and keeping it to one argument is what makes it credible
    that the two arms differ in nothing else.
    """
    from audible.draft.board import DraftBoard, DraftEntry
    from audible.models.player import PlayerProjection
    from audible.value.replacement import compute_vorp
    from audible.value.scarcity import scarcity_values

    rows = season_board.rows
    n = len(rows)
    span = TOP_POINTS - BOTTOM_POINTS
    points = [TOP_POINTS - span * (r.rank - 1) / max(1, n - 1) for r in rows]
    if shuffle is not None:
        shuffle.shuffle(points)

    projections = [
        PlayerProjection(
            player_id=f"ffc{r.rank:04d}",
            name=r.name,
            primary_position=r.position,
            eligible_positions=frozenset({r.position}),
            team=r.team or None,
            points=pts,
        )
        for r, pts in zip(rows, points, strict=True)
    ]
    vorp_entries, _levels = compute_vorp(projections, config)
    scarcity = scarcity_values(projections, config)

    vorp_by_id = {e.projection.player_id: e.vorp for e in vorp_entries}
    ranked = sorted(vorp_by_id, key=lambda pid: (-vorp_by_id[pid], pid))
    vorp_rank = {pid: i + 1 for i, pid in enumerate(ranked)}
    adp_sorted = sorted(rows, key=lambda r: r.adp)
    adp_rank = {f"ffc{r.rank:04d}": i + 1 for i, r in enumerate(adp_sorted)}

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
            vorp=vorp_by_id[f"ffc{r.rank:04d}"],
            vorp_rank=vorp_rank[f"ffc{r.rank:04d}"],
            consensus_rank=vorp_rank[f"ffc{r.rank:04d}"],
            opp_rank=vorp_rank[f"ffc{r.rank:04d}"],
            deviation=False,
            scarcity=scarcity.get(f"ffc{r.rank:04d}", 0.0),
            scarcity_rank=vorp_rank[f"ffc{r.rank:04d}"],
            adp=r.adp,
            adp_rank=adp_rank[f"ffc{r.rank:04d}"],
            value=0,
            flags=(),
        )
        for r, pts in zip(rows, points, strict=True)
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
    calls: int = 0

    def choose(self, overall: int, taken: Sequence[int], rows: Sequence[Any]) -> int:
        """The board index Audible would take. Returns -1 when it has no legal answer."""
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
        call = urgency.the_call(
            rows_for_call,
            next_pick=view.my_next_pick,
            needs=urgency.roster_needs(
                state_mod._roster_slots(view), self.service.config.slot_eligibility
            ),
            available_entries=available,
        )
        self.calls += 1
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
    )


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

    @property
    def advantage(self) -> float:
        """Points-for minus the mean opponent seat. The paired quantity every arm reports."""
        return self.points_for - (
            sum(self.opponent_points) / len(self.opponent_points)
            if self.opponent_points
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
) -> ArmResult:
    """One draft with Audible in *seat*, then one bootstrapped season scored on it.

    PAIRING. Every stream is derived from *seed* alone: the room uses `seed`, the shuffle
    permutation uses `seed`, and the bootstrap uses `seed`. So `real` and `shuffle` at seed 7
    face the identical opponent field and the identical weekly draws, and their difference
    isolates the arm.
    """
    if arm not in ("real", "shuffle", "leaky-shuffle"):
        raise ValueError(f"unknown arm {arm!r}")

    shuffle_rng = random.Random(seed) if arm == "shuffle" else None
    holder = build_seat(
        season_board, config, week_table.byes, state_dir, seat=seat, shuffle=shuffle_rng
    )
    from audible.draft.live import Pick

    rows = season_board.rows

    def chooser(overall: int, taken: Sequence[int], rows: Sequence[Any]) -> int:
        return holder.choose(overall, taken, rows)

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
        holder.service._invalidate()

    picks = room.simulate_draft(
        season_board,
        fit,
        seed,
        chooser=chooser,
        chooser_seat=seat,
        observer=observe,
    )

    rng = random.Random(seed)
    rosters: dict[int, list[room.SimPick]] = {}
    for p in picks:
        rosters.setdefault(p.seat, []).append(p)

    mine, unresolved = weekly.resolve_roster(rosters[seat], season_board, week_table)
    mine_points = weekly.points_for(random.Random(seed * 1_000_003), week_table, mine)
    opponents: list[float] = []
    for other in sorted(rosters):
        if other == seat:
            continue
        roster, _ = weekly.resolve_roster(rosters[other], season_board, week_table)
        opponents.append(
            weekly.points_for(random.Random(seed * 1_000_003 + other), week_table, roster)
        )
    del rng

    return ArmResult(
        arm=arm, season=season, seed=seed, seat=seat,
        points_for=mine_points, opponent_points=tuple(opponents),
        unresolved=unresolved, picks=tuple(picks), calls=holder.calls,
    )


def mean_and_interval(values: Sequence[float]) -> tuple[float, float, float]:
    """(mean, lo, hi) at roughly 95%, from the normal approximation to the standard error.

    A bare point estimate is never reported. With paired arms the quantity is a difference of
    means over the same seeds, so the standard error is the one of the paired differences and
    not of either arm on its own.
    """
    import statistics as st

    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean = st.mean(values)
    if n == 1:
        return mean, mean, mean
    sem = st.stdev(values) / n**0.5
    return mean, mean - 1.96 * sem, mean + 1.96 * sem


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
