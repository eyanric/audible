"""Live draft decision surface (Draft-Day Tool, §2-3).

Consumes the gate-validated board + live Sleeper draft picks and answers the questions you
actually have on the clock: who's the best available *for my exact slots*, will he survive
to my next pick (grab-now vs can-wait), is a positional run on (the superflex QB run is the
big one), and am I at a tier cliff. Advisory tilts (opp±/riser/vac) ride along as flags.

No new modeling -- pure application of the value layer to live state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config.schema import LeagueConfig
from .board import DraftBoard, DraftEntry

_POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"]


@dataclass(frozen=True, slots=True)
class Pick:
    pick_no: int
    round: int
    draft_slot: int
    player_id: str


def parse_picks(raw: list[dict[str, Any]]) -> list[Pick]:
    picks: list[Pick] = []
    for r in raw:
        pid = r.get("player_id")
        if not pid:
            continue
        picks.append(Pick(
            pick_no=int(r.get("pick_no") or 0), round=int(r.get("round") or 0),
            draft_slot=int(r.get("draft_slot") or 0), player_id=str(pid),
        ))
    return sorted(picks, key=lambda p: p.pick_no)


def snake_pick_numbers(slot: int, teams: int, rounds: int) -> list[int]:
    """Overall pick numbers for a draft slot in a snake draft."""
    out: list[int] = []
    for rnd in range(1, rounds + 1):
        offset = slot if rnd % 2 == 1 else (teams - slot + 1)
        out.append((rnd - 1) * teams + offset)
    return out


def next_pick_after(slot: int, teams: int, rounds: int, current_pick: int) -> int | None:
    """The slot's next overall pick number at or after ``current_pick`` (None if none left)."""
    return next((n for n in snake_pick_numbers(slot, teams, rounds) if n >= current_pick), None)


def unfilled_slots(my_entries: list[DraftEntry], config: LeagueConfig) -> list[str]:
    """My remaining starting slots after greedily placing my picks (most-specific slot first)."""
    slots = list(config.starting_slots)
    filled = [False] * len(slots)
    for entry in sorted(my_entries, key=lambda e: -e.points):
        best_idx = -1
        best_key: tuple[int, str] | None = None
        for i, name in enumerate(slots):
            if filled[i]:
                continue
            eligible = config.slot_eligibility[name]
            if entry.position in eligible:
                key = (len(eligible), name)
                if best_key is None or key < best_key:
                    best_key, best_idx = key, i
        if best_idx >= 0:
            filled[best_idx] = True
    return [slots[i] for i in range(len(slots)) if not filled[i]]


@dataclass(frozen=True, slots=True)
class Candidate:
    entry: DraftEntry
    grab_now: bool  # unlikely to survive to my next pick
    fills_need: bool  # eligible for one of my unfilled starting slots


@dataclass(frozen=True, slots=True)
class LiveView:
    current_pick: int
    on_the_clock: int | None  # draft slot on the clock
    my_next_pick: int | None
    picks_until_me: int | None
    my_roster: list[str]  # names of my picks
    unfilled: list[str]  # my remaining starting slots
    best_available: list[Candidate]  # ranked by league value
    recommendations: list[Candidate]  # best available that fill a need, on the clock
    runs: list[str]
    cliffs: list[str]


def _ordered_positions(config: LeagueConfig) -> list[str]:
    return [p for p in _POS_ORDER if p in config.positions]


def compute_view(
    board: DraftBoard,
    picks: list[Pick],
    my_slot: int,
    config: LeagueConfig,
    rounds: int,
    *,
    recent_window: int | None = None,
    cliff_pts: float = 15.0,
    top: int = 18,
) -> LiveView:
    teams = config.num_teams
    by_id = {e.player_id: e for e in board.entries}
    drafted = {p.player_id for p in picks}
    available = [e for e in board.entries if e.player_id not in drafted]  # already value-ranked

    current_pick = len(picks) + 1
    on_clock = my_slot_on_clock(current_pick, teams)
    my_next = next_pick_after(my_slot, teams, rounds, current_pick) if my_slot else None
    picks_until = (my_next - current_pick) if my_next is not None else None

    my_entries = [
        by_id[p.player_id] for p in picks if p.draft_slot == my_slot and p.player_id in by_id
    ]
    unfilled = unfilled_slots(my_entries, config)
    needs = {pos for slot in unfilled for pos in config.slot_eligibility[slot]}

    gone: set[str] = set()
    if picks_until and picks_until > 0:
        by_adp = sorted((e for e in available if e.adp is not None), key=lambda e: e.adp or 0.0)
        gone = {e.player_id for e in by_adp[:picks_until]}

    def candidate(e: DraftEntry) -> Candidate:
        return Candidate(e, grab_now=e.player_id in gone, fills_need=e.position in needs)

    best = [candidate(e) for e in available[:top]]
    recs = [candidate(e) for e in available if e.position in needs][:6]

    # scarcity-run alerts over the recent window
    window = recent_window or teams
    recent = picks[-window:]
    counts: dict[str, int] = {}
    for p in recent:
        e = by_id.get(p.player_id)
        if e is not None:
            counts[e.position] = counts.get(e.position, 0) + 1
    runs: list[str] = []
    superflex = "SUPER_FLEX" in config.starting_slots
    for pos, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        if c >= max(3, round(window * 0.4)):
            tag = "  <<< SUPERFLEX QB RUN" if pos == "QB" and superflex else ""
            runs.append(f"{pos} run: {c} of last {len(recent)} picks{tag}")

    # tier cliffs: best available at a position alone before a points drop
    cliffs: list[str] = []
    for pos in _ordered_positions(config):
        at_pos = [e for e in available if e.position == pos]
        if len(at_pos) >= 2 and (at_pos[0].points - at_pos[1].points) >= cliff_pts:
            gap = at_pos[0].points - at_pos[1].points
            cliffs.append(f"{pos}: {at_pos[0].name} is the last before a {gap:.0f}-pt drop")

    return LiveView(
        current_pick=current_pick, on_the_clock=on_clock, my_next_pick=my_next,
        picks_until_me=picks_until, my_roster=[e.name for e in my_entries], unfilled=unfilled,
        best_available=best, recommendations=recs, runs=runs, cliffs=cliffs,
    )


def my_slot_on_clock(current_pick: int, teams: int) -> int:
    """Which draft slot is on the clock for ``current_pick`` (snake order)."""
    rnd = (current_pick - 1) // teams + 1
    idx = (current_pick - 1) % teams
    return idx + 1 if rnd % 2 == 1 else teams - idx
