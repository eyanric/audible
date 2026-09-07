"""TASK B1 -- fit the opponent room from real drafts, then gate it before anything is
measured inside it.

ONE CLAIM: an eight-bot room built here drafts like the real eight-team room does. Nothing
measured inside a wrong room means anything, and the failure is silent, so the room is
validated against statistics chosen before the first synthetic draft ran.

Read-only against every cached input. Builds no replay engine and scores no season -- B1
ends at a validated room. (``--cost`` does put audible's real board in seat 6 for 16 sampled
pick states, to time ``compute_view``. It measures; it decides nothing and scores nothing.)

    uv run --extra nflverse python -m sim.room --cost
    uv run --extra nflverse python -m sim.room --inject adp-only     # exits 1 when it fires


WHY ADP ALONE CANNOT BE THE ROOM
--------------------------------
Measured across the five completed league-6012 drafts (640 picks, 2021-2025). Both rows in
season order, 2021 first:

    real room, K + D/ST inside 128 picks:   17, 16, 16, 17, 17
    strict-ADP room, same statistic:         4,  2,  1,  0,  4

That gap is not noise in a sigma and no sigma closes it. Fantasy Football Calculator's first
kicker each year sits at ADP rank 138-143 on a board only 180-224 deep, so ZERO kickers are
inside the top 128 by ADP in any of the five seasons -- and the real room took eight every
year. A real manager takes exactly one kicker and one defence (39 of 40 team-seasons take
exactly one K, 38 of 40 exactly one D/ST) because the starting lineup has one slot for each
and the draft is the only place to fill them.

THE TWO CLOCKS. Mean of (actual pick - FFC ADP rank), by position, over 622 joined picks:

    RB   +0.8    WR   -4.6    TE   -3.6    QB   +6.3      <- skill: essentially zero
    K   -54.4    DEF -44.7                                <- specialists: half a draft early

Rescale the same ADP by rounds instead of by rank -- FFC serves TWELVE-team ADP for every
season (``meta.teams`` reads 12 in all five pinned files, whatever the ``teams=`` parameter
said), and this room is eight, so ADP rank r maps to eight-team pick (r-1)*8/12+1 -- and the
means invert:

    RB  +17.1    WR  +15.6    TE  +20.2    QB  +27.5
    K    -0.8    DEF  +5.1                                <- specialists: essentially zero

Skill players are drafted on the RANK clock: an eight-team room consumes the consensus board
in the same order a twelve-team room does, because player supply does not care how many
teams there are. Kickers and defences are drafted on the ROUND clock: a manager takes one
"near the end", and near-the-end is a different overall pick number in an eight-team room
than in a twelve-team one. A kicker's mean ADP rank is 161.8 and his mean pick is 107.4, at a
pick sd of 12.4 against 32-36 for the skill positions. WHICH kicker barely matters; WHEN is
nearly fixed.

The statistic the code actually classifies on is a count, not a correlation -- see
``SUPPLY_RATIO_CUT``, which also records the correlation test this replaced and the two ways
adversarial review refuted it.


THE MECHANISM, and where it departs from ``ralpherz/fantasy-draft-sim``
-----------------------------------------------------------------------
That project's ``draft_engine.bot_pick`` is the starting point, read at commit 6917dfa. Four
non-contiguous lines, with the elision marked:

    noise = self.np_rng.normal(0.0, avail["stdev"].clip(lower=0.5).to_numpy())
    ...
    need_shift = avail["position"].isin(needs).to_numpy() * -3.0
    effective_pick = avail["adp_rank_overall"].to_numpy() + noise + need_shift
    choice = avail.iloc[int(np.argmin(effective_pick))]["player_id"]

One property is adopted -- the argmin over an effective pick -- and three are changed.

CHANGED 1 -- K and D/ST leave the board entirely, and there is NO NEED SHIFT anywhere in this
module. ralpherz gives every position one mechanism and a -3.0 pull toward unfilled starter
slots; that pull cannot move a kicker from ADP rank 140 into the top 128, and the real room
does it eight times a year. This model was first written that way with the pull FITTED rather
than assumed (mu = -54.4 for K, -44.7 for D/ST) and it still failed validation, because a
constant rank-space offset preserves rank ORDER. Reproducible today with
``simulate_draft(schedule_specialists=False)``: the 2025 Cincinnati defence -- ADP rank 56 off
five recorded drafts, a thin-sample artefact rather than a market -- comes off the board in
ROUND 1 more often than in any other round (8 of 20 seeds; the mode is 1 and round 7 happens
once), and the first defence lands in round 8.1 -- measured over 250 drafts -- against
a real 11-13.

CHANGED 2 -- the noise is drawn ONCE PER PLAYER PER DRAFT, not once per pick. Redrawing per
pick makes each selection an argmin over a fresh draw for every available player, so with a
hundred candidates in play someone always lands two sigma low. MEASURED, and not where you
would expect: over 500 paired drafts the realised spread of (pick - ADP rank) is 21.56
per-draft against 21.62 per-pick, a difference of 0.29% that is not distinguishable from
zero, because most of that 21.6 is structure rather than draw -- at ``sigma_scale=0`` both
give 13.65. What per-pick actually breaks is pick ORDER: ``first QB round`` falls to 2.34
against a real 3.0-5.0, which fails G2 at -9.7 sem. Run ``--sampler per-pick`` and read it
off. An earlier version of this docstring claimed per-pick widened the spread and sent the
reader to the spread line to see it; the module's own instrumentation refutes that, and this
paragraph is the correction.

CHANGED 3 -- a feasibility deadline. With as many picks left as unfilled starting slots, a
seat must spend them there, most specific slot first. Zero fitted parameters. Both halves
earn their place against ``deadline=False``: without it 42.6% of seats finish unable to field
a legal lineup, usually missing a tight end or a quarterback, and with the schedule off as
well that is 77.5% and 0-6 seats a draft with no kicker at all. All forty real team-seasons
could field a lineup. This matters more than it looks: the positional TOTALS were right
without it and only the allocation across seats was wrong, so no draft-level statistic in the
pre-registered set could see it.

CHANGED 4 -- the legality filter runs INSIDE the argmin rather than ahead of the draw. With
per-draft sampling the noise is drawn for the whole board up front, so caps and slot
eligibility are applied when a bot chooses, not before it rolls. Same effect, different
order, and worth stating because ralpherz's filter genuinely does precede its draw.


WHAT THE FIT IS
---------------
Every PARAMETER below is computed from the pinned files at run time; none is a literal. Three
STRUCTURAL constants are literals and they do change the fit's output, so they are named here
rather than left to be discovered: ``SUPPLY_RATIO_CUT`` (1.0, which is a meaning rather than
a threshold), ``MIN_CELL`` (12, the pooling floor) and ``BUCKETS`` (the four round bands).

  supply_ratio[position]    drafted in 128 picks / that position in the top 128 by ADP.
                            Decides which regime a position is in. Reported per season.

  BOARD positions (QB, RB, WR, TE as measured)
  mu[position]              mean of (actual pick - ADP rank). A constant offset on the board
                            value. QB's +6.3 is real: an eight-team 1-QB room waits on
                            quarterbacks relative to a twelve-team board. Only the
                            DIFFERENCES between positions are identifiable -- adding a
                            constant to every mu cancels inside the argmin.
  sigma[position][bucket]   sd of the same quantity after removing mu[position], keyed on the
                            round bucket of ``Fit.expected_pick``. Cells thinner than
                            MIN_CELL pool up to the position marginal, and the report names
                            every cell that pooled.

  SCHEDULED positions (K, DEF as measured)
  pick_mu / pick_sd         mean and sd of the actual PICK NUMBER. Each seat draws its own
                            target for each such slot, once per draft. mu plays no part in
                            when these go; the board order only decides WHICH kicker, among
                            those still available.

  BOTH
  cap[position]             the largest number of that position any one team took in any of
                            the forty team-seasons. Honest about its role: the K and D/ST caps
                            (both 2) NEVER BIND, because a seat stops needing a specialist
                            once it holds one. What holds K+DEF to exactly 16 is the
                            one-starting-slot need test plus the deadline, not the cap.


WHAT THIS ROOM DOES NOT DO
--------------------------
Left unfixed on purpose: closing a held-out miss by adding a mechanism is what tuning a gate
to pass looks like from the inside.

Found by the held-out check:

* It never takes a second kicker or a second defence, so K+DEF inside 128 is exactly 16 in
  every synthetic draft while the real room ranged 16-17 and hit 17 in three seasons of five.
  Three of eighty real team-slot-seasons took a second.
* It under-disperses in a loose season. Sigma is pooled across all five, so 2021 (board 224
  rows, real spread 27.5) and 2025 (221 rows, 26.8) come out near 20.8 like the rest. Board
  depth and real spread are rank-monotone across all five seasons and a pooled sigma cannot
  express that.
* 2023's first defence went in round 11 against a synthetic band of 12-14. The schedule is
  pooled across seasons for the same reason sigma is. 2025 is the other season whose first K
  and first D/ST both came a round early, and it is covered.

Known independently of the held-out check:

* It cannot draft anyone who is not on the FFC board, and 18 of 640 real picks (2.8%) were
  not. By position that is 7 K, 4 DEF, 3 RB, 3 WR, 1 QB -- kickers are the plurality, not
  defences.
* THE SPREAD GATE IS COMPARED AGAINST A TRUNCATED TARGET. The real ``pick-ADP spread`` is
  computed over joined picks only, because an off-board pick has no rank. Give every
  off-board pick the most conservative rank possible -- board depth + 1 -- and the real range
  becomes 22.5-37.7 rather than 20.6-27.5, and the synthetic 21.95 FAILS. The pass on that
  line depends on the truncation, and the fitted sigma is a FLOOR on true market dispersion
  rather than an estimate of it.
* THE GATE'S RESOLUTION ON THE SPECIALIST SCHEDULE IS ABOUT ONE ROUND. Shifting ``pick_mu``
  for K and D/ST by -8 picks -- a full round early -- still passes all six pre-registered
  statistics; -12 and +8 do not. "Room resembles real" means "within about a round", and no
  more than that.

Two limits that hold regardless and belong in every sim report: no vintage preseason
projections exist for any season, so this measures ORDERING and never the projections; and
bots fitted to ADP are not people -- they do not stack, reach for their own players, or panic.


LEAKAGE (G5)
------------
The board is FFC's ADP, whose ``meta.end_date`` is 1-4 September, 3 to 8 days before that
season's first game. Positions come from the DynastyProcess crosswalk and ESPN's served
ranks, which are identity rather than outcome. Nothing derived from a completed season
touches the board or the bots.

Enforced rather than intended: ``SeasonBoard`` carries a ``provenance`` tuple and every board
passes ``assert_pre_draft`` before a draft runs -- each source on the ``PRE_DRAFT_SOURCES``
allowlist, and ``asof`` strictly before kickoff, which is derived rather than tabulated. A
board built from end-of-season points fails on the source name and would fail again on the
date; ``sim/test_g_room.py::test_i4_*`` builds exactly that board and shows both firing.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import LIVE_CACHE, SIM_CACHE
from .adp_join import DEF_POSITIONS, normalize

SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)

# The league the drafts come from, and the room being modelled. Both ESPN leagues carry the
# same nine starting slots and sixteen rounds (leagues/espn_davis_drive.toml,
# leagues/espn_green_hope.toml), which is what makes 6012's completed drafts behavioural
# evidence for Green Hope rather than evidence about a different game.
LEAGUE_ID: str = "6012"
TEAMS: int = 8
ROUNDS: int = 16
PICKS: int = TEAMS * ROUNDS

# FFC serves TWELVE-team ADP for every season regardless of the `teams=` parameter --
# `meta.teams` reads 12 in all five pinned files whose names say 8. Named, because the round
# rescaling in the docstring depends on it and a silent change would move every offset.
ADP_TEAMS: int = 12

# Starting slots, from both ESPN league configs, and identical in the two. There is no "need
# shift" in this module; these drive two things only -- whether a seat still OWES a scheduled
# slot, and what the feasibility deadline must spend its last picks on.
STARTING_SLOTS: tuple[str, ...] = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K")
SLOT_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "QB": ("QB",),
    "RB": ("RB",),
    "WR": ("WR",),
    "TE": ("TE",),
    "FLEX": ("RB", "WR", "TE"),
    "DEF": ("DEF",),
    "K": ("K",),
}

# Position vocabularies disagree across the three sources, and all three meet in one join.
# FFC writes PK/DEF, ESPN and the crosswalk write K/DEF, and `adp_join.DEF_POSITIONS`
# already names the defence spellings.
_POSITION_CANON: dict[str, str] = {"PK": "K", "DST": "DEF", "D/ST": "DEF"}

# There is NO spelling disagreement to fix between the two vocabularies. All 29 team
# abbreviations FFC has ever put on a defence appear verbatim in nflverse `team_abbr`; the
# residue (ATL, LA, LV, OAK, SD, STL, TEN) is nflverse-only. An earlier version of this file
# carried an `LA -> LAR` alias and a comment calling it the only disagreement and claiming it
# rescued the 2021 Rams D/ST. Both halves were false: the real failure is many-to-one
# NICKNAME collapse, handled in `nick_to_abbr`, and the alias could never fire because the
# collision overwrote LA with STL before it was consulted. Kept as a named absence so the
# next reader does not re-add it.

# Round buckets for the sigma fit, as the handoff specifies them.
BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("r1-4", 1, 4), ("r5-8", 5, 8), ("r9-12", 9, 12), ("r13-16", 13, 16),
)

# A (position, bucket) cell thinner than this pools up to the position marginal. Twenty-four
# cells over ~620 joined picks leaves several near-empty -- no kicker goes in rounds 1-4 in
# any season -- and a standard deviation of three points is noise wearing a number's clothes.
# Every pooled cell is named in the report rather than pooled silently.
MIN_CELL: int = 12

# Sources allowed to reach a board. The allowlist IS the leakage gate (G5): anything derived
# from a completed season is absent by construction rather than by review.
PRE_DRAFT_SOURCES: frozenset[str] = frozenset({"ffc_adp", "ff_playerids", "espn_ranks"})

# A position is drafted off the BOARD while the board supplies at least as many of it as the
# room takes, and on a SCHEDULE once the room takes MORE of it than the board's first 128
# rows hold. The cut is exactly 1.0 and it is not a tuning knob: above it, the picks cannot
# have come off the board, because the board did not contain them.
#
#   supply ratio = (drafted in 128 picks) / (that position in the top 128 by ADP)
#   pooled 2021-2025:  K inf (0 available, 41 drafted)   DEF 3.82 (11 available, 42 drafted)
#                      WR 0.93   RB 0.88   TE 0.87   QB 0.78
#
# THIS REPLACED A CORRELATION TEST, and the reason is worth keeping. The first version keyed
# on corr(ADP rank, actual pick) -- +0.87 to +0.90 for the skill positions against +0.36 to
# +0.39 for K and D/ST -- and read the gap as two regimes. Adversarial review refuted it two
# ways. That correlation is invariant to the very 8/12 round rescaling the two-clock story is
# about (both clocks are linear in rank, so r cannot tell them apart, and the rescaled
# correlation agrees to six decimal places). And the gap is range restriction: restricted to
# the specialists' own rank-and-pick box, WR comes in at r=-0.11 slope +0.03 and RB at
# r=-0.50 slope -0.28, BOTH BELOW the specialists. A Fisher-z interval on K is
# [+0.03, +0.62], so the old 0.60 cut sat inside it.
#
# The supply ratio has none of that. It is a count over the whole board and the whole draft,
# nothing is conditioned on, and 1.0 is a meaning rather than a threshold. The correlations
# are still computed and still reported, as diagnostics, with that caveat attached.
SUPPLY_RATIO_CUT: float = 1.0

def kickoff(season: int) -> date:
    """The season's first regular-season game: the Thursday after Labor Day.

    Derived rather than tabulated, because a per-season literal is a thing that can go stale
    without anything noticing. Checked against all five: 2021-09-09, 2022-09-08, 2023-09-07,
    2024-09-05, 2025-09-04, which are the real openers.

    It is the cutoff the leakage guard measures a board's `asof` against, and the margin is
    not generous -- FFC's 2025 sample closes 2025-09-01, three days before kickoff -- so
    moving this by a week would either admit a leaky board or reject a clean one.
    """
    labor_day = next(
        date(season, 9, d) for d in range(1, 8) if date(season, 9, d).weekday() == 0
    )
    return date.fromordinal(labor_day.toordinal() + 3)


SEASON_START: dict[int, date] = {s: kickoff(s) for s in SEASONS}


# --- inputs -----------------------------------------------------------------------------


def canon_position(raw: str | None) -> str:
    """One position vocabulary out of FFC's, ESPN's and the crosswalk's."""
    up = (raw or "").upper()
    if up in DEF_POSITIONS:
        return "DEF"
    return _POSITION_CANON.get(up, up)


def resolve_input(name: str) -> tuple[Path, str]:
    """Locate a pinned input, preferring sim's own root, and say which root it came from.

    Reading the cockpit's root is deliberate and safe -- nothing in this module opens a file
    for writing, and every input it wants is re-fetchable. It is NOT the same convention as
    `probe.py`, which points at ``SIM_CACHE`` with no fallback and needs an explicit
    ``--cache`` to read the live root; this falls back silently, and in a checkout without
    ``data/sim-cache`` every input comes from the cockpit's root. What is not safe is reading
    one root while reporting another, so the root is returned and the report prints it on its
    first line.
    """
    for root, label in ((SIM_CACHE, "sim"), (LIVE_CACHE, "live")):
        path = root / name
        if path.exists():
            return path, label
    raise FileNotFoundError(
        f"{name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}. B1 does not substitute a "
        f"nearby season or a different source for a missing input."
    )


@dataclass(frozen=True, slots=True)
class BoardRow:
    """One player on a season's pre-draft board."""

    rank: int
    adp: float
    name: str
    position: str
    team: str
    stdev: float
    times_drafted: int

    @property
    def key(self) -> str:
        """Join key: team abbreviation for a defence, normalised name for a person."""
        return f"DEF:{self.team}" if self.position == "DEF" else f"P:{normalize(self.name)}"


@dataclass(frozen=True, slots=True)
class SeasonBoard:
    """A season's board, plus what it was built from and as of when."""

    season: int
    rows: tuple[BoardRow, ...]
    provenance: tuple[str, ...]
    asof: date
    roots: tuple[str, ...]

    def by_key(self) -> dict[str, BoardRow]:
        return {r.key: r for r in self.rows}


def load_board(season: int) -> SeasonBoard:
    """The FFC ADP board for *season*, ranked by ADP.

    Rank is derived from a sort rather than read off the file. FFC ships the list in ADP
    order already, but a rank that comes from the sort cannot silently disagree with the ADP
    it is meant to summarise.
    """
    path, root = resolve_input(f"ffc_adp_standard_8_{season}.json")
    blob = json.loads(path.read_text(encoding="utf-8"))
    meta = blob.get("meta") or {}
    players = sorted(blob.get("players", []), key=lambda p: float(p["adp"]))
    rows = tuple(
        BoardRow(
            rank=i,
            adp=float(p["adp"]),
            name=str(p["name"]),
            position=canon_position(str(p.get("position") or "")),
            team=str(p.get("team") or "").upper(),
            stdev=float(p.get("stdev") or 0.0),
            times_drafted=int(p.get("times_drafted") or 0),
        )
        for i, p in enumerate(players, start=1)
    )
    end = str(meta.get("end_date") or "")
    asof = date.fromisoformat(end) if end else date(season, 12, 31)
    return SeasonBoard(season=season, rows=rows, provenance=("ffc_adp",), asof=asof, roots=(root,))


def assert_pre_draft(board: SeasonBoard) -> None:
    """G5. A board carrying anything a completed season produced does not run.

    Two independent checks, because either alone is escapable: an unlisted SOURCE, and an
    ``asof`` that is not strictly before the season's first game. A board assembled from
    end-of-season points fails the first on its source name and the second on its date.
    """
    unknown = sorted(set(board.provenance) - PRE_DRAFT_SOURCES)
    if unknown:
        raise ValueError(
            f"{board.season} board carries non-pre-draft source(s) {unknown}; the opponent "
            f"model may use only information that existed before that season's draft. "
            f"Allowed: {sorted(PRE_DRAFT_SOURCES)}"
        )
    start = kickoff(board.season)
    if board.asof >= start:
        raise ValueError(
            f"{board.season} board is as of {board.asof}, which is not before that season's "
            f"first game ({start}). A board that has seen a snap of the season it drafts for "
            f"is leakage even when every source name is allowed."
        )


@dataclass(frozen=True, slots=True)
class RealPick:
    season: int
    overall: int
    round: int
    team_id: int
    player_id: str
    name: str
    position: str


def espn_identity() -> dict[str, tuple[str, str]]:
    """ESPN player id -> (name, position), from sources that predate every draft here.

    Two sources, and both are needed. The crosswalk carries 8149 espn ids and no team
    defences at all (``ff_playerids`` has zero DEF rows); ESPN's served ranks carry the
    thirty-two negative defence ids but exist only for 2023-2025. Defence ids are stable
    across seasons, so the later files resolve the earlier drafts' defences. Together they
    resolve all 640 picks, measured, with none left over.
    """
    import polars as pl

    path, _ = resolve_input("nflverse/ff_playerids.parquet")
    frame = pl.read_parquet(path)
    out: dict[str, tuple[str, str]] = {}
    for espn_id, name, position in frame.select(["espn_id", "name", "position"]).iter_rows():
        if espn_id is None or name is None:
            continue
        out[str(espn_id).strip()] = (str(name), canon_position(position))
    for season in (2023, 2024, 2025):
        try:
            ranks_path, _ = resolve_input(f"espn_ranks_{LEAGUE_ID}_{season}.json")
        except FileNotFoundError:
            continue
        for pid, row in json.loads(ranks_path.read_text(encoding="utf-8")).items():
            out.setdefault(
                str(pid), (str(row.get("name") or ""), canon_position(row.get("position")))
            )
    return out


def ffc_defence_abbrs() -> frozenset[str]:
    """Every team abbreviation FFC has ever put on a defence, across the five seasons."""
    out: set[str] = set()
    for season in SEASONS:
        for row in load_board(season).rows:
            if row.position == "DEF":
                out.add(row.team)
    return frozenset(out)


def nick_to_abbr(ffc_abbrs: frozenset[str] | None = None) -> dict[str, str]:
    """Steelers -> PIT. ESPN names a defence by nickname; FFC keys it by abbreviation.

    THE COLLISION IS THE WHOLE FUNCTION. ``teams.parquet`` carries 36 rows for 32 franchises
    because three relocated: Rams appear as LA, LAR and STL, Chargers as LAC and SD, Raiders
    as LV and OAK. A plain dict comprehension keyed on the nickname keeps whichever row comes
    last, which is STL, SD and OAK -- none of which any modern FFC board uses. That silently
    turned the 2021 Rams D/ST, which FFC lists at ADP 105.4, into an off-board pick.

    So the tie is broken against FFC's OWN vocabulary: where a nickname maps to several
    abbreviations, take the one FFC actually writes. If none of them is (a franchise FFC has
    never listed a defence for), keep the first, which is the current abbreviation.
    """
    import polars as pl

    path, _ = resolve_input("nflverse/teams.parquet")
    frame = pl.read_parquet(path)
    known = ffc_defence_abbrs() if ffc_abbrs is None else ffc_abbrs
    candidates: dict[str, list[str]] = {}
    for abbr, nick in frame.select(["team_abbr", "team_nick"]).iter_rows():
        candidates.setdefault(str(nick), []).append(str(abbr).upper())
    out: dict[str, str] = {}
    for nick, abbrs in candidates.items():
        preferred = [a for a in abbrs if a in known]
        out[nick] = preferred[0] if preferred else abbrs[0]
    return out


def load_real_draft(season: int, identity: dict[str, tuple[str, str]]) -> tuple[RealPick, ...]:
    """The completed league-6012 draft for *season*: 128 picks, every position resolved."""
    path, _ = resolve_input(f"espn_draft_{LEAGUE_ID}_{season}.json")
    picks: list[RealPick] = []
    unresolved: list[str] = []
    for row in json.loads(path.read_text(encoding="utf-8")):
        pid = str(row["player_id"])
        hit = identity.get(pid)
        if hit is None:
            unresolved.append(pid)
            continue
        name, position = hit
        picks.append(
            RealPick(
                season=season,
                overall=int(row["overall"]),
                round=int(row["round"]),
                team_id=int(row["team_id"]),
                player_id=pid,
                name=name,
                position=position,
            )
        )
    if unresolved:
        raise ValueError(
            f"{season}: {len(unresolved)} of {len(picks) + len(unresolved)} picks resolve to no "
            f"position ({unresolved[:5]}). A draft carrying unpositioned picks makes every "
            f"positional statistic below quietly wrong."
        )
    return tuple(picks)


def pick_join_key(pick: RealPick, nicks: dict[str, str]) -> str:
    """The same key shape ``BoardRow.key`` produces, computed from an ESPN pick."""
    if pick.position == "DEF":
        nick = pick.name.replace("D/ST", "").strip()
        return f"DEF:{nicks.get(nick, nick.upper())}"
    return f"P:{normalize(pick.name)}"


# --- the fit ----------------------------------------------------------------------------


def bucket_of(round_no: int) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= round_no <= hi:
            return name
    return BUCKETS[-1][0] if round_no > BUCKETS[-1][2] else BUCKETS[0][0]


def round_of(pick_no: float, teams: int = TEAMS) -> int:
    """The round a (possibly fractional, possibly out-of-range) pick number falls in."""
    return max(1, min(ROUNDS, int((max(1.0, pick_no) - 1) // teams) + 1))


@dataclass(frozen=True, slots=True)
class JoinedPick:
    """A real pick that resolved to a board row, and the delta that fits the model."""

    season: int
    overall: int
    round: int
    position: str
    rank: int
    adp: float
    delta: float  # actual pick - ADP rank


@dataclass(frozen=True, slots=True)
class Fit:
    """Everything the room needs, all of it measured.

    Two regimes, and which position lands in which is decided by a measurement rather than
    by a preference -- see ``fit_room`` and ``rank_corr``.
    """

    # Rank clock -- positions whose ADP rank predicts their pick.
    mu: dict[str, float]
    sigma: dict[str, dict[str, float]]
    cell_n: dict[str, dict[str, int]]
    pooled: tuple[str, ...]
    # Round clock -- positions whose ADP rank does not.
    scheduled: frozenset[str]
    pick_mu: dict[str, float]
    pick_sd: dict[str, float]
    supply_ratio: dict[str, float]
    supply_avail: dict[str, int]
    supply_drafted: dict[str, int]
    supply_by_season: dict[str, tuple[float, ...]]
    rank_corr: dict[str, float]
    rank_slope: dict[str, float]
    # Shared.
    caps: dict[str, int]
    cap_hist: dict[str, dict[int, int]]
    joined: int
    total: int
    offboard: dict[str, int]
    position_n: dict[str, int]
    round_sigma: dict[str, float]
    round_n: dict[str, int]
    seasons: tuple[int, ...]

    def sigma_for(self, position: str, expected_pick: float) -> float:
        bucket = bucket_of(round_of(expected_pick))
        by_bucket = self.sigma.get(position)
        if not by_bucket:
            return self.round_sigma.get(bucket, 1.0)
        return by_bucket[bucket]

    def expected_pick(self, position: str, rank: int) -> float:
        """Where this player is expected to go, which is what keys his sigma cell.

        For a SCHEDULED position that is the fitted schedule, not anything about his rank --
        a kicker at ADP rank 220 and one at 140 both go around pick 107, so both draw from
        the same cell. Keying those off `rank + mu` was a real defect: it gave the two
        kickers sigma 23.1 and 10.7 for no reason a measurement supports, and it made `mu`
        silently load-bearing for positions the report calls it unused for.
        """
        if position in self.scheduled:
            return self.pick_mu[position]
        return rank + self.mu.get(position, 0.0)


def _sd(values: Sequence[float]) -> float:
    """Population standard deviation; 0.0 for a degenerate sample rather than a raise."""
    return st.pstdev(values) if len(values) > 1 else 0.0


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """(correlation, OLS slope) of *ys* on *xs*. (nan, nan) on a degenerate sample."""
    if len(xs) < 2:
        return float("nan"), float("nan")
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx == 0 or syy == 0:
        return float("nan"), float("nan")
    return sxy / (sxx * syy) ** 0.5, sxy / sxx


def fit_room(
    seasons: Sequence[int] = SEASONS, *, teams: int = TEAMS, rounds: int = ROUNDS
) -> Fit:
    """Fit the room from the completed drafts. No literals, no knobs, two regimes.

    WHICH REGIME A POSITION IS IN IS MEASURED, NOT CHOSEN, and the measurement is a count:

        supply ratio = (drafted in 128 picks) / (that position in the top 128 by ADP)

        K   inf  (0 available across all five seasons, 41 drafted)
        DEF 3.82 (11 available, 42 drafted)      <- above 1: cannot have come off the board
        WR  0.93   RB 0.88   TE 0.87   QB 0.78   <- below 1: the board had more than enough

    Above 1.0 the room takes more of a position than the board's first 128 rows contain, so
    those picks did not come off the board and no board model can produce them. Every season
    agrees: the lowest specialist ratio in any single season is 2.25 (2025 D/ST) and the
    highest skill ratio is 1.00, so the cut has a factor of 2.25 of clearance and 1.0 is a
    meaning rather than a tuned number.

    ``rank_corr`` and ``rank_slope`` are still computed and reported, but as DIAGNOSTICS
    ONLY, because they cannot carry this decision -- see SUPPLY_RATIO_CUT for the two ways
    adversarial review refuted them.

    Two earlier designs are recorded here because they are the reason the parameterisation is
    what it is, and both failed against real drafts:

    * K and D/ST on the rank clock, as a fitted constant offset (mu = -54.4 for K, -46.2 for
      D/ST). A constant rank-space offset preserves rank ORDER, so the 2025 Cincinnati
      defence -- ADP rank 56 off five recorded drafts, an artefact of FFC's thin sample
      rather than a market -- was most often taken in ROUND 1, and the first defence landed
      in round 8.1 against a real 11-13. Reproducible today with
      ``simulate_draft(schedule_specialists=False)``.
    * Correlation as the classifier, described above.
    """
    identity = espn_identity()
    nicks = nick_to_abbr()

    joined: list[JoinedPick] = []
    offboard: Counter[str] = Counter()
    total = 0
    per_team: dict[tuple[int, int], Counter[str]] = {}

    for season in seasons:
        board = load_board(season)
        assert_pre_draft(board)
        index = board.by_key()
        for pick in load_real_draft(season, identity):
            total += 1
            per_team.setdefault((season, pick.team_id), Counter())[pick.position] += 1
            row = index.get(pick_join_key(pick, nicks))
            if row is None:
                offboard[pick.position] += 1
                continue
            joined.append(
                JoinedPick(
                    season=season, overall=pick.overall, round=pick.round,
                    position=pick.position, rank=row.rank, adp=row.adp,
                    delta=float(pick.overall - row.rank),
                )
            )

    by_position: dict[str, list[JoinedPick]] = {}
    for jp in joined:
        by_position.setdefault(jp.position, []).append(jp)

    rank_corr: dict[str, float] = {}
    rank_slope: dict[str, float] = {}
    for pos, rows in by_position.items():
        corr, slope = _pearson([r.rank for r in rows], [r.overall for r in rows])
        rank_corr[pos] = corr
        rank_slope[pos] = slope

    # THE CLASSIFIER. Counted over the whole board and the whole draft, per season and
    # pooled, so nothing is conditioned on and range restriction cannot reach it.
    avail: Counter[str] = Counter()
    drafted: Counter[str] = Counter()
    per_season: dict[str, list[float]] = {}
    for season in seasons:
        board = load_board(season)
        a = Counter(r.position for r in board.rows[: teams * rounds])
        d = Counter(p.position for p in load_real_draft(season, identity))
        avail.update(a)
        drafted.update(d)
        for pos in set(a) | set(d):
            per_season.setdefault(pos, []).append(
                d[pos] / a[pos] if a[pos] else float("inf")
            )
    supply_ratio = {
        pos: (drafted[pos] / avail[pos] if avail[pos] else float("inf"))
        for pos in set(avail) | set(drafted)
    }
    scheduled = frozenset(p for p, r in supply_ratio.items() if r > SUPPLY_RATIO_CUT)

    pick_mu = {p: st.mean([r.overall for r in by_position[p]]) for p in scheduled}
    pick_sd = {p: _sd([float(r.overall) for r in by_position[p]]) for p in scheduled}

    mu = {pos: st.mean([j.delta for j in rows]) for pos, rows in by_position.items()}
    position_n = {pos: len(rows) for pos, rows in by_position.items()}

    # Round marginals, over residuals, so a pooled cell falls back to something fitted too.
    round_res: dict[str, list[float]] = {}
    for jp in joined:
        round_res.setdefault(bucket_of(jp.round), []).append(jp.delta - mu[jp.position])
    round_sigma = {b: _sd(v) for b, v in round_res.items()}
    round_n = {b: len(v) for b, v in round_res.items()}

    # The joint cells. The bucket is keyed on the EXPECTED pick (rank + mu), not on where the
    # player actually landed: the simulator has to look sigma up before it knows where anyone
    # goes, and keying on the outcome would make the fit unusable at run time.
    cells: dict[str, dict[str, list[float]]] = {}
    for jp in joined:
        expected = jp.rank + mu[jp.position]
        cells.setdefault(jp.position, {}).setdefault(bucket_of(round_of(expected)), []).append(
            jp.delta - mu[jp.position]
        )

    sigma: dict[str, dict[str, float]] = {}
    cell_n: dict[str, dict[str, int]] = {}
    pooled: list[str] = []
    for pos, rows in by_position.items():
        pos_sigma = _sd([j.delta - mu[pos] for j in rows])
        sigma[pos] = {}
        cell_n[pos] = {}
        for name, _lo, _hi in BUCKETS:
            values = cells.get(pos, {}).get(name, [])
            cell_n[pos][name] = len(values)
            if len(values) >= MIN_CELL:
                sigma[pos][name] = _sd(values)
            else:
                sigma[pos][name] = pos_sigma
                pooled.append(f"{pos}/{name} n={len(values)}")

    caps = {pos: 0 for pos in by_position}
    cap_hist: dict[str, dict[int, int]] = {}
    for counts in per_team.values():
        for pos, n in counts.items():
            caps[pos] = max(caps.get(pos, 0), n)
            cap_hist.setdefault(pos, {}).setdefault(n, 0)
            cap_hist[pos][n] += 1

    return Fit(
        mu=mu, sigma=sigma, cell_n=cell_n, pooled=tuple(pooled),
        scheduled=scheduled, pick_mu=pick_mu, pick_sd=pick_sd,
        supply_ratio=supply_ratio, supply_avail=dict(avail), supply_drafted=dict(drafted),
        supply_by_season={k: tuple(v) for k, v in per_season.items()},
        rank_corr=rank_corr, rank_slope=rank_slope,
        caps=caps, cap_hist=cap_hist,
        joined=len(joined), total=total, offboard=dict(offboard), position_n=position_n,
        round_sigma=round_sigma, round_n=round_n, seasons=tuple(seasons),
    )


# --- the room ---------------------------------------------------------------------------


def slot_on_clock(pick_no: int, teams: int = TEAMS) -> int:
    """Which seat owns *pick_no* in a snake. Same convention as ``harness.slot_on_clock``."""
    rnd = (pick_no - 1) // teams + 1
    idx = (pick_no - 1) % teams
    return idx + 1 if rnd % 2 == 1 else teams - idx


_SLOT_COUNTS: dict[str, int] = {s: STARTING_SLOTS.count(s) for s in STARTING_SLOTS}
# Most specific first, so the deadline spends its last picks on the slot fewest players can
# fill. FLEX takes three positions and is the one to leave until last.
_SLOT_ORDER: tuple[str, ...] = tuple(
    sorted(_SLOT_COUNTS, key=lambda s: (len(SLOT_ELIGIBILITY[s]), s))
)


class _Roster:
    """One bot's roster: position counts, and which starting slots are still empty.

    Placement is greedy into the most specific open slot first, so a third receiver takes
    FLEX rather than pretending a WR slot is still open. That is what makes ``unfilled``
    mean "starting slots this seat still cannot field" rather than "positions it is light at".
    """

    __slots__ = ("counts", "filled")

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.filled: Counter[str] = Counter()

    def add(self, position: str) -> None:
        self.counts[position] += 1
        for slot in STARTING_SLOTS:
            if position in SLOT_ELIGIBILITY[slot] and self.filled[slot] < _SLOT_COUNTS[slot]:
                self.filled[slot] += 1
                return

    def needs(self, position: str) -> bool:
        """True while some starting slot this position fills is still empty."""
        return any(
            position in SLOT_ELIGIBILITY[slot] and self.filled[slot] < _SLOT_COUNTS[slot]
            for slot in STARTING_SLOTS
        )

    def unfilled(self) -> list[str]:
        """Every still-empty starting slot, most specific first, one entry per empty seat."""
        out: list[str] = []
        for slot in _SLOT_ORDER:
            out.extend([slot] * (_SLOT_COUNTS[slot] - self.filled[slot]))
        return out


@dataclass(frozen=True, slots=True)
class SimPick:
    overall: int
    round: int
    seat: int
    rank: int
    position: str
    name: str

    def as_row(self) -> dict[str, Any]:
        return {
            "overall": self.overall, "round": self.round, "seat": self.seat,
            "rank": self.rank, "position": self.position, "name": self.name,
        }


def simulate_draft(
    board: SeasonBoard,
    fit: Fit,
    seed: int,
    *,
    teams: int = TEAMS,
    rounds: int = ROUNDS,
    sigma_scale: float = 1.0,
    sampler: str = "per-draft",
    schedule_specialists: bool = True,
    deadline: bool = True,
    check_leakage: bool = True,
) -> tuple[SimPick, ...]:
    """One synthetic draft. Same seed, same board, same fit -> byte-identical picks.

    Two regimes, per ``fit_room``:

    * BOARD positions get a draft-day value of ``rank + mu + N(0, sigma)``, drawn once per
      player per draft, and a bot takes the lowest legal one.
    * SCHEDULED positions (K and D/ST, as measured) are not on the board at all. Each seat
      draws, once per draft, the pick at which it intends to fill each such slot, from that
      position's fitted ``N(pick_mu, pick_sd)``. On the clock at or past that target, and
      still short of the slot, it takes the best available player there.

    A FEASIBILITY DEADLINE overrides both. With as many picks left as unfilled STARTING
    SLOTS -- all nine of them, not only the scheduled two -- the seat must spend them there,
    most specific slot first. Zero fitted parameters, and it is not a preference: all forty
    real team-seasons finished able to field a legal lineup, and both halves of the deadline
    were put in because the room without them produced something the real record contains
    zero times. Without the scheduled half, 1-5 seats a draft (mean 3.0) finished with no
    kicker. Without the board half, 34.8% of seats finished unable to start a lineup at all,
    usually missing a tight end or a quarterback -- and no draft-level statistic could see
    it, because the positional TOTALS were right and only the allocation across seats was
    wrong.

    The keyword switches drive the failure injections and the ablations the report prints
    alongside its verdict. The VERDICT itself is always computed at ``sigma_scale=1.0``,
    ``sampler="per-draft"``, ``schedule_specialists=True``, ``deadline=True``; anything run at
    other settings is labelled as an ablation where it is printed.
    """
    if check_leakage:
        assert_pre_draft(board)
    if sampler not in ("per-draft", "per-pick"):
        raise ValueError(f"unknown sampler {sampler!r}; expected per-draft or per-pick")

    rng = random.Random(seed)
    rows = board.rows
    n = len(rows)
    if n < teams * rounds:
        raise ValueError(
            f"{board.season} board holds {n} players; a {teams}x{rounds} draft needs "
            f"{teams * rounds}. A room that runs out of board is not a room."
        )

    scheduled = fit.scheduled if schedule_specialists else frozenset()
    mu = [fit.mu.get(r.position, 0.0) for r in rows]
    sig = [
        fit.sigma_for(r.position, fit.expected_pick(r.position, r.rank)) * sigma_scale
        for r in rows
    ]

    # Board value. Sampled once per player per draft -- see CHANGED 2 in the module docstring.
    if sampler == "per-draft":
        value = [
            rows[i].rank + mu[i] + (rng.normalvariate(0.0, sig[i]) if sig[i] > 0 else 0.0)
            for i in range(n)
        ]
    else:
        value = [rows[i].rank + mu[i] for i in range(n)]

    # Each seat's intended pick for each scheduled slot. Drawn in a fixed (seat, position)
    # order so the draw sequence -- and therefore the whole draft -- is a function of the
    # seed alone.
    order = sorted(scheduled)
    targets: list[dict[str, float]] = []
    for _seat in range(teams):
        targets.append(
            {
                pos: rng.normalvariate(fit.pick_mu[pos], fit.pick_sd[pos] * sigma_scale)
                for pos in order
            }
        )

    caps = fit.caps
    taken = bytearray(n)
    rosters = [_Roster() for _ in range(teams)]
    picks: list[SimPick] = []
    picks_left = {seat: rounds for seat in range(1, teams + 1)}

    def _best(seat_roster: _Roster, positions: frozenset[str] | None) -> int:
        best, best_score = -1, 0.0
        for i in range(n):
            if taken[i]:
                continue
            row = rows[i]
            if positions is None:
                if row.position in scheduled:
                    continue
            elif row.position not in positions:
                continue
            if seat_roster.counts[row.position] >= caps.get(row.position, rounds):
                continue
            score = value[i]
            if sampler == "per-pick" and sig[i] > 0:
                score += rng.normalvariate(0.0, sig[i])
            if best < 0 or score < best_score:
                best, best_score = i, score
        return best

    for overall in range(1, teams * rounds + 1):
        seat = slot_on_clock(overall, teams)
        roster = rosters[seat - 1]
        remaining = picks_left[seat]

        due = sorted(
            (pos for pos in order if roster.needs(pos) and targets[seat - 1][pos] <= overall),
            key=lambda p: targets[seat - 1][p],
        )
        unfilled = roster.unfilled()

        best = -1
        if deadline and len(unfilled) >= remaining and unfilled:
            # THE DEADLINE, over every starting slot rather than only the scheduled ones.
            # `unfilled` is most-specific-first, so the last picks go to the slot fewest
            # players can fill and FLEX is left until last. Without this over the BOARD
            # slots too, 34.8% of synthetic seats finished unable to field a legal lineup --
            # usually no tight end or no quarterback -- which none of forty real
            # team-seasons did, and which no draft-level statistic can see.
            best = _best(roster, frozenset(SLOT_ELIGIBILITY[unfilled[0]]))
        if best < 0 and due:
            best = _best(roster, frozenset({due[0]}))
        if best < 0:
            best = _best(roster, None)
        if best < 0:
            # Nothing legal off the board: fall back to anything legal at all, so a thin
            # board runs the draft out rather than aborting it.
            best = _best(roster, frozenset(fit.caps))
        if best < 0:
            raise RuntimeError(
                f"{board.season} seed {seed}: seat {seat} has no legal pick at {overall}. "
                f"The caps and the board disagree about what a roster can hold."
            )

        taken[best] = 1
        row = rows[best]
        roster.add(row.position)
        picks_left[seat] = remaining - 1
        picks.append(
            SimPick(
                overall=overall, round=(overall - 1) // teams + 1, seat=seat,
                rank=row.rank, position=row.position, name=row.name,
            )
        )
    return tuple(picks)


def draft_digest(picks: Sequence[SimPick]) -> str:
    """A stable serialisation, so G4 compares bytes rather than a summary of bytes."""
    import hashlib

    blob = json.dumps([p.as_row() for p in picks], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- the pre-registered statistics -------------------------------------------------------
#
# Fixed before any synthetic draft was run, and none of them is what the fit optimises. The
# one weak member is the spread, which sigma IS fitted to -- it is reported as a
# self-consistency check and labelled as such, never as independent evidence.


@dataclass(frozen=True, slots=True)
class Stats:
    first_qb_round: float
    first_k_round: float
    first_def_round: float
    kdef_in_128: float
    runs_3plus: float
    delta_spread: float

    def as_row(self) -> dict[str, float]:
        return {
            "first QB round": self.first_qb_round,
            "first K round": self.first_k_round,
            "first DEF round": self.first_def_round,
            "K+DEF in 128": self.kdef_in_128,
            "runs of 3+": self.runs_3plus,
            "pick-ADP spread": self.delta_spread,
        }


def _first_round(rows: Sequence[tuple[int, int, str]], position: str, rounds: int) -> float:
    """Round the first *position* goes, or ``rounds + 1`` when it never does.

    A position that is never taken must not read as "taken in the last round" -- that would
    make the naive ADP room, which takes no kicker at all, look like a room that takes one
    late. ``rounds + 1`` is outside the draft and says so.
    """
    hits = [r for _o, r, p in rows if p == position]
    return float(min(hits)) if hits else float(rounds + 1)


def _runs_3plus(rows: Sequence[tuple[int, int, str]]) -> int:
    """Maximal consecutive-pick runs of one position, length 3 or more, counted once each."""
    ordered = [p for _o, _r, p in sorted(rows)]
    total = 0
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[i]:
            j += 1
        if j - i + 1 >= 3:
            total += 1
        i = j + 1
    return total


def stats_of(
    rows: Sequence[tuple[int, int, str]],
    deltas: Sequence[float],
    rounds: int = ROUNDS,
    teams: int = TEAMS,
) -> Stats:
    """*rows* is (overall, round, position); *deltas* is (pick - ADP rank) where defined.

    The K+DEF window follows *teams* x *rounds* rather than the module-level PICKS, so a room
    of another shape counts specialists over its own draft rather than over this one's.
    """
    kdef = sum(1 for o, _r, p in rows if p in ("K", "DEF") and o <= teams * rounds)
    return Stats(
        first_qb_round=_first_round(rows, "QB", rounds),
        first_k_round=_first_round(rows, "K", rounds),
        first_def_round=_first_round(rows, "DEF", rounds),
        kdef_in_128=float(kdef),
        runs_3plus=float(_runs_3plus(rows)),
        delta_spread=_sd(deltas),
    )


def real_stats(season: int, identity: dict[str, tuple[str, str]], nicks: dict[str, str]) -> Stats:
    board = load_board(season)
    index = board.by_key()
    picks = load_real_draft(season, identity)
    rows = [(p.overall, p.round, p.position) for p in picks]
    deltas = [
        float(p.overall - row.rank)
        for p in picks
        if (row := index.get(pick_join_key(p, nicks))) is not None
    ]
    return stats_of(rows, deltas)


def sim_stats(picks: Sequence[SimPick]) -> Stats:
    rows = [(p.overall, p.round, p.position) for p in picks]
    deltas = [float(p.overall - p.rank) for p in picks]
    return stats_of(rows, deltas)


def adp_only_stats(board: SeasonBoard) -> Stats:
    """The known-bad model: take the top 128 by ADP, in order. Injection 1's target."""
    rows = [
        (i, (i - 1) // TEAMS + 1, r.position)
        for i, r in enumerate(board.rows[:PICKS], start=1)
    ]
    deltas = [0.0] * len(rows)
    return stats_of(rows, deltas)


STAT_LABELS: dict[str, str] = {
    "first_qb_round": "first QB round",
    "first_k_round": "first K round",
    "first_def_round": "first DEF round",
    "kdef_in_128": "K+DEF in 128",
    "runs_3plus": "runs of 3+",
    "delta_spread": "pick-ADP spread",
}

# What each pre-registered statistic actually tests, once the fit is known. Recorded here
# because a gate that a fit determines is not evidence, and the difference has to survive
# being read by someone who did not build this.
#
#   free  -- the fit targets nothing resembling it. Genuine out-of-sample evidence even
#            in-sample.
#   semi  -- a consequence of a fitted STRUCTURE rather than of a fitted VALUE. For
#            `K+DEF in 128` that structure is the one-starting-slot need test plus the
#            feasibility deadline. NOT the roster caps: K and D/ST are capped at 2 and the
#            cap never binds, because a seat stops needing a specialist once it holds one.
#   fitted-- the fit targets this quantity directly. Only the held-out run says anything.
SHORT: dict[str, str] = {
    "first QB round": "QB",
    "first K round": "K",
    "first DEF round": "DEF",
    "K+DEF in 128": "K+DEF",
    "runs of 3+": "runs",
    "pick-ADP spread": "spread",
}

STAT_KIND: dict[str, str] = {
    "first_qb_round": "free",
    "first_k_round": "fitted",
    "first_def_round": "fitted",
    "kdef_in_128": "semi",
    "runs_3plus": "free",
    "delta_spread": "fitted",
}


def _pct(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


@dataclass(frozen=True, slots=True)
class Comparison:
    """Synthetic distribution against the real per-season range, one statistic."""

    name: str
    kind: str
    synthetic: float
    sem: float
    syn_lo: float
    syn_hi: float
    real_lo: float
    real_hi: float
    real_values: tuple[float, ...]

    @property
    def passes(self) -> bool:
        """In-sample form: does the synthetic mean land inside the real five-season range?"""
        return self.real_lo <= self.synthetic <= self.real_hi

    @property
    def margin_sem(self) -> float:
        """How many standard errors the mean sits inside the nearer bound. Negative = outside.

        Reported because two of the six statistics pass by sitting at the very bottom of the
        real range, and "pass" alone would hide that. The synthetic mean is a Monte Carlo
        estimate over a fixed seed set, so it is exactly reproducible but not exact -- a
        margin under about two standard errors is a pass that a different seed count could
        have reported differently, and it is labelled.
        """
        inside = min(self.synthetic - self.real_lo, self.real_hi - self.synthetic)
        if self.sem <= 0:
            # Zero variance is not infinite confidence, and reporting it as `+inf sem` hid
            # the single weakest line in the battery: K+DEF is exactly 16 in every synthetic
            # draft, sits exactly ON the real lower bound, and misses in three of five
            # held-out seasons. A degenerate statistic gets whatever slack it actually has
            # and 0.0 when it has none, so `pass(marginal)` can still fire on it.
            return inside if inside > 0 else 0.0
        return inside / self.sem

    @property
    def covers(self) -> bool:
        """Held-out form, and the one that means something on a single season.

        Asks the question the other way round -- could this room have produced that season?
        -- because a single season is one number, and demanding that a mean over twenty
        synthetic drafts equal one integer exactly is not a test, it is arithmetic that
        always fails. The band is the synthetic 5th-95th percentile.
        """
        return self.syn_lo <= self.real_lo <= self.syn_hi


def compare(synthetic: Sequence[Stats], real: Sequence[Stats]) -> list[Comparison]:
    out: list[Comparison] = []
    for name in Stats.__slots__:
        syn = [getattr(s, name) for s in synthetic]
        vals = tuple(getattr(s, name) for s in real)
        sem = _sd(syn) / len(syn) ** 0.5 if len(syn) > 1 else 0.0
        out.append(
            Comparison(
                name=STAT_LABELS[name], kind=STAT_KIND[name], synthetic=st.mean(syn), sem=sem,
                syn_lo=_pct(syn, 0.05), syn_hi=_pct(syn, 0.95),
                real_lo=min(vals), real_hi=max(vals), real_values=vals,
            )
        )
    return out


def holdout(seeds: int = 50, sampler: str = "per-draft") -> list[tuple[int, list[Comparison]]]:
    """Leave-one-season-out. The only part of G2 that is evidence for the fitted statistics.

    Refit on four seasons, draft the fifth season's board with those parameters, compare
    against what that season's room actually did. The held-out season contributed nothing to
    mu, sigma, the pick schedule or the caps, so a statistic the fit targets in-sample is
    genuinely out-of-sample here.

    The comparison range is that ONE season's value, not the five-season range, so it is a
    much tighter test than the in-sample line -- a room that merely averages the five
    seasons fails it.
    """
    identity = espn_identity()
    nicks = nick_to_abbr()
    out: list[tuple[int, list[Comparison]]] = []
    for held in SEASONS:
        fit = fit_room([s for s in SEASONS if s != held])
        board = load_board(held)
        synthetic = [
            sim_stats(simulate_draft(board, fit, seed, sampler=sampler)) for seed in range(seeds)
        ]
        out.append((held, compare(synthetic, [real_stats(held, identity, nicks)])))
    return out


# --- the report --------------------------------------------------------------------------


def _fmt(x: float) -> str:
    return f"{x:.1f}"


def report(seeds: int = 50, sampler: str = "per-draft") -> tuple[list[str], bool]:
    out: list[str] = []
    fit = fit_room()
    identity = espn_identity()
    nicks = nick_to_abbr()

    boards = {s: load_board(s) for s in SEASONS}
    roots = sorted({r for b in boards.values() for r in b.roots})
    out.append(f"input root(s): {', '.join(roots)}  (sim={SIM_CACHE}, live={LIVE_CACHE})")
    out.append(f"seasons: {', '.join(str(s) for s in SEASONS)}  picks: {fit.total}")
    out.append(
        f"joined to board: {fit.joined}/{fit.total} "
        f"({fit.joined / fit.total * 100:.1f}%)  off-board by position: "
        f"{dict(sorted(fit.offboard.items()))}"
    )
    out.append("")

    out.append("G1 -- the fit, all of it measured")
    out.append(
        f"  which clock each position is on. supply ratio = drafted / available in the top "
        f"{PICKS} by ADP, cut at {SUPPLY_RATIO_CUT}:"
    )
    for pos in sorted(fit.supply_ratio, key=lambda p: -fit.supply_ratio[p]):
        clock = "SCHEDULE" if pos in fit.scheduled else "board"
        per = "/".join(
            "inf" if v == float("inf") else f"{v:.2f}" for v in fit.supply_by_season[pos]
        )
        ratio = fit.supply_ratio[pos]
        out.append(
            f"    {pos:4s} avail={fit.supply_avail.get(pos, 0):4d} "
            f"drafted={fit.supply_drafted.get(pos, 0):4d}  "
            f"ratio={'inf' if ratio == float('inf') else f'{ratio:.2f}':>6s}  -> {clock}"
        )
        out.append(f"         by season: {per}")
    out.append(
        "  diagnostics only -- corr(ADP rank, actual pick) and its slope. These do NOT decide"
    )
    out.append(
        "  the split: they are invariant to the 8/12 rescale and confounded by range"
    )
    out.append("  restriction. See SUPPLY_RATIO_CUT.")
    for pos in sorted(fit.rank_corr, key=lambda p: -fit.rank_corr[p]):
        out.append(
            f"    {pos:4s} n={fit.position_n[pos]:4d}  r={fit.rank_corr[pos]:+.3f}  "
            f"slope={fit.rank_slope[pos]:+.3f}"
        )
    out.append("  scheduled positions, fitted pick distribution:")
    for pos in sorted(fit.scheduled):
        out.append(
            f"    {pos:4s} pick ~ N(mu={fit.pick_mu[pos]:.1f}, sd={fit.pick_sd[pos]:.1f}) "
            f"-> rounds {round_of(fit.pick_mu[pos] - fit.pick_sd[pos])}-"
            f"{round_of(fit.pick_mu[pos] + fit.pick_sd[pos])}"
        )
    out.append("  mu = mean(actual pick - ADP rank), the board positions' offset:")
    for pos in sorted(fit.mu):
        # Genuinely unused for a scheduled position: `Fit.expected_pick` keys their sigma
        # off `pick_mu`, and their board value never decides when they go. Printed anyway,
        # because it is the number that made the two clocks visible in the first place.
        tag = "  (not used: scheduled)" if pos in fit.scheduled else ""
        out.append(f"    {pos:4s} n={fit.position_n[pos]:4d}  mu={fit.mu[pos]:+7.1f}{tag}")
    out.append("  sigma by position x round bucket (of the expected pick):")
    for pos in sorted(fit.sigma):
        cells = "  ".join(
            f"{b}={fit.sigma[pos][b]:5.1f}(n={fit.cell_n[pos][b]:d})" for b, _l, _h in BUCKETS
        )
        out.append(f"    {pos:4s} {cells}")
    out.append("  sigma by round bucket, pooled over positions (the fallback):")
    out.append(
        "    "
        + "  ".join(
            f"{b}={fit.round_sigma.get(b, 0.0):5.1f}(n={fit.round_n.get(b, 0)})"
            for b, _l, _h in BUCKETS
        )
    )
    out.append(f"  cells pooled to the position marginal (n<{MIN_CELL}): {', '.join(fit.pooled)}")
    out.append("  roster caps, = max any one team took in 40 team-seasons:")
    for pos in sorted(fit.caps):
        hist = ", ".join(f"{k}x{v}" for k, v in sorted(fit.cap_hist[pos].items()))
        out.append(f"    {pos:4s} cap={fit.caps[pos]}   per-team counts: {hist}")
    out.append("")

    real = [real_stats(s, identity, nicks) for s in SEASONS]
    synthetic: list[Stats] = []
    for season in SEASONS:
        for seed in range(seeds):
            synthetic.append(
                sim_stats(simulate_draft(boards[season], fit, seed, sampler=sampler))
            )

    out.append(f"G2 -- room validation, {len(synthetic)} synthetic drafts ({sampler} sampler)")
    out.append("  in-sample: synth mean [5th-95th pct] vs the real five-season range")
    comparisons = compare(synthetic, real)
    verdict = True
    for c in comparisons:
        flag = "pass" if c.passes else "FAIL"
        if c.passes and c.margin_sem < 2.0:
            flag = "pass(marginal)"
        out.append(
            f"    {c.name:16s} synth={c.synthetic:6.2f}+-{c.sem:.2f} "
            f"[{_fmt(c.syn_lo)}-{_fmt(c.syn_hi)}]  "
            f"real={_fmt(c.real_lo)}-{_fmt(c.real_hi)}  "
            f"{flag} {c.margin_sem:+.1f}sem  ({c.kind})"
        )
        if not c.passes:
            verdict = False
    for name in Stats.__slots__:
        vals = "; ".join(
            f"{s}={_fmt(getattr(r, name))}" for s, r in zip(SEASONS, real, strict=True)
        )
        out.append(f"    real by season, {STAT_LABELS[name]:16s} {vals}")
    out.append("")
    out.append("  HELD OUT: refit on four seasons, draft the fifth. The evidence that counts")
    out.append("  for anything the fit targets -- the held season is in none of it.")
    out.append("  Read as: does that season's real value fall inside the synthetic 5-95 band?")
    held_pass = 0
    held_total = 0
    misses: list[str] = []
    for season, comps in holdout(seeds=seeds, sampler=sampler):
        marks = []
        for c in comps:
            held_total += 1
            ok = c.covers
            held_pass += 1 if ok else 0
            marks.append(f"{SHORT[c.name]}={'ok' if ok else 'MISS'}")
            if not ok:
                misses.append(
                    f"        {season} {c.name:16s} real={_fmt(c.real_lo)} outside synth "
                    f"[{_fmt(c.syn_lo)}-{_fmt(c.syn_hi)}] (mean {_fmt(c.synthetic)})"
                )
        out.append(f"    {season}: " + "  ".join(marks))
    out.extend(misses)
    out.append(f"    held-out: {held_pass}/{held_total} season-statistics covered")
    out.append("")
    out.append(f"  verdict: room {'resembles' if verdict else 'DOES NOT resemble'} real")
    out.append("")

    out.append("G3 -- specialists, against the model that failed by 4x")
    naive = [adp_only_stats(boards[s]) for s in SEASONS]
    syn_kdef = st.mean([s.kdef_in_128 for s in synthetic])
    real_kdef = [r.kdef_in_128 for r in real]
    naive_kdef = [n.kdef_in_128 for n in naive]
    out.append(
        f"  K+DEF in 128   real={min(real_kdef):.0f}-{max(real_kdef):.0f}  "
        f"synth={syn_kdef:.1f}  strict-ADP={min(naive_kdef):.0f}-{max(naive_kdef):.0f}"
    )
    out.append(
        "  strict-ADP by season: "
        + "; ".join(f"{s}={n.kdef_in_128:.0f}" for s, n in zip(SEASONS, naive, strict=True))
    )
    for label, kwargs in (
        ("SCHEDULE OFF (specialists back on the board clock)", {"schedule_specialists": False}),
        ("DEADLINE OFF", {"deadline": False}),
    ):
        ablated = [
            sim_stats(simulate_draft(boards[s], fit, seed, **kwargs))
            for s in SEASONS
            for seed in range(max(2, seeds // 8))
        ]
        out.append(
            f"  ablation, {label}: K+DEF={st.mean([a.kdef_in_128 for a in ablated]):.1f}  "
            f"first DEF round={st.mean([a.first_def_round for a in ablated]):.1f}"
        )
    out.append(
        "  (schedule off overshoots -- on the board clock a -54/-45 offset makes specialists"
    )
    out.append(
        "  look like top-60 players, so seats take them early and the cap of 2 starts to bind.)"
    )
    return out, verdict


INJECTIONS: tuple[str, ...] = (
    "adp-only", "no-schedule", "no-deadline", "wide-sigma", "leaky-board", "seed",
)


def inject(name: str, seeds: int = 4) -> tuple[list[str], bool]:
    """Corrupt one mechanism and report whether the gates notice.

    Returns ``False`` when the injection FIRED -- the corrupted room went red, which is the
    outcome that says the gate is doing something -- and ``True`` when the corrupted room
    passed anyway, which says the gate proves nothing. ``main`` maps the firing case to exit
    code 1 so a caller can read it without parsing text.

    An injection that passes on empty output proves nothing either, so each of these runs the
    real gates over a real corrupted room and prints what actually came back.
    """
    out: list[str] = [f"INJECTION: {name}"]
    fit = fit_room()
    identity = espn_identity()
    nicks = nick_to_abbr()
    boards = {s: load_board(s) for s in SEASONS}
    real = [real_stats(s, identity, nicks) for s in SEASONS]
    real_lo = min(r.kdef_in_128 for r in real)
    real_hi = max(r.kdef_in_128 for r in real)

    if name == "leaky-board":
        leaky = SeasonBoard(
            season=2024, rows=boards[2024].rows, provenance=("player_stats_2024",),
            asof=date(2025, 2, 1), roots=boards[2024].roots,
        )
        try:
            simulate_draft(leaky, fit, 1)
        except ValueError as exc:
            out.append(f"  guard raised: {exc}")
            out.append("  INJECTION FIRED: G5 refused a board built from a completed season")
            return out, False
        out.append("  the leakage guard did NOT fire -- G5 is inert")
        return out, True

    if name == "seed":
        digests = [draft_digest(simulate_draft(boards[2024], fit, s)) for s in range(4)]
        out.extend(f"  seed {i}: {d[:16]}" for i, d in enumerate(digests))
        if len(set(digests)) == len(digests):
            out.append(
                "  INJECTION FIRED: four seeds, four distinct drafts -- G4 is not a constant"
            )
            return out, False
        out.append("  seeds collided; G4 would pass on a constant")
        return out, True

    if name == "adp-only":
        stats = [adp_only_stats(boards[s]) for s in SEASONS]
        kdef = [s.kdef_in_128 for s in stats]
        out.append(f"  K+DEF in 128 by season: {[int(k) for k in kdef]}")
        out.append(f"  real range: {real_lo:.0f}-{real_hi:.0f}")
        if max(kdef) < real_lo:
            out.append(
                f"  INJECTION FIRED: G3 fails -- strict ADP order takes {min(kdef):.0f}-"
                f"{max(kdef):.0f} specialists against a real {real_lo:.0f}-{real_hi:.0f}"
            )
            return out, False
        out.append("  strict ADP order landed in the real range; G3 is not measuring this")
        return out, True

    kwargs: dict[str, Any] = {}
    if name == "no-schedule":
        kwargs["schedule_specialists"] = False
    elif name == "no-deadline":
        kwargs["deadline"] = False
    elif name == "wide-sigma":
        kwargs["sigma_scale"] = 8.0
    else:
        raise ValueError(f"unknown injection {name!r}; expected one of {INJECTIONS}")

    synthetic = [
        sim_stats(simulate_draft(boards[s], fit, seed, **kwargs))
        for s in SEASONS
        for seed in range(seeds)
    ]
    broken = [c for c in compare(synthetic, real) if not c.passes]
    for c in compare(synthetic, real):
        out.append(
            f"  {c.name:16s} synth={_fmt(c.synthetic):>6s}  "
            f"real={_fmt(c.real_lo)}-{_fmt(c.real_hi)}  {'pass' if c.passes else 'FAIL'}"
        )
    if broken:
        out.append(
            f"  INJECTION FIRED: G2 fails on {', '.join(c.name for c in broken)}"
        )
        return out, False
    out.append("  every pre-registered statistic still passed; the gates are inert")
    return out, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim.room",
        description="Fit the opponent room from real drafts and validate it. Builds no replay.",
    )
    parser.add_argument("--seeds", type=int, default=50, help="synthetic drafts per season")
    parser.add_argument("--sampler", choices=("per-draft", "per-pick"), default="per-draft")
    parser.add_argument("--cost", action="store_true", help="also report per-draft wall clock")
    parser.add_argument(
        "--inject", choices=INJECTIONS, default=None,
        help="corrupt one mechanism and report whether the gates notice (exits 1 when they do)",
    )
    args = parser.parse_args(argv)

    if args.inject:
        lines, held = inject(args.inject, seeds=args.seeds)
        for line in lines:
            print(line)
        # 1 means the injection fired -- the gate went red, which is the desired outcome.
        # 0 would mean the corrupted room passed, i.e. the gate proves nothing.
        return 1 if not held else 0

    lines, ok = report(seeds=args.seeds, sampler=args.sampler)
    for line in lines:
        print(line)

    if args.cost:
        print("")
        for line in cost_report(seeds=args.seeds):
            print(line)
    return 0 if ok else 1


# --- TASK 3, the cost ---------------------------------------------------------------------


def cost_report(seeds: int = 50) -> list[str]:
    """Where a simulated draft's wall clock goes, and whether the board survives a seed.

    Two costs, roughly 190x apart per draft, which is the finding:

    * THE ROOM ALONE -- eight bots over a 180-224 row ADP board. This is what B1 built.
    * AUDIBLE IN THE SEAT -- one ``compute_view`` per pick over the real 3,304-row Green
      Hope board. This is what B2 adds and what B3 has to size its seed count against, so it
      is measured here rather than guessed at in B3.

    The design question, answered by measurement rather than opinion: can the board be built
    once per season and reused across seeds? Both boards are checked, sim's by digest and
    audible's by running the same board object through two independent draft states and
    confirming the second is unaffected by the first.
    """
    out: list[str] = []
    t0 = time.perf_counter()
    fit = fit_room()
    t_fit = time.perf_counter() - t0

    t0 = time.perf_counter()
    boards = {s: load_board(s) for s in SEASONS}
    t_board = (time.perf_counter() - t0) / len(SEASONS)

    board = boards[2025]
    t0 = time.perf_counter()
    for seed in range(seeds):
        simulate_draft(board, fit, seed)
    t_draft = (time.perf_counter() - t0) / seeds

    out.append("TASK 3 -- per-draft cost")
    out.append("  the room alone (what B1 built):")
    out.append(f"    fit, once over all five seasons:  {t_fit * 1000:8.1f} ms")
    out.append(f"    board build, per season:          {t_board * 1000:8.1f} ms")
    out.append(f"    one simulated draft, 128 picks:   {t_draft * 1000:8.1f} ms")
    total = t_board + t_draft
    out.append(
        f"    share:  board {t_board / total * 100:4.1f}%   "
        f"ordering {t_draft / total * 100:4.1f}%"
    )
    reused = draft_digest(simulate_draft(board, fit, 7))
    rebuilt = draft_digest(simulate_draft(load_board(2025), fit, 7))
    out.append(
        f"    board reusable across seeds: "
        f"{'yes' if reused == rebuilt else 'NO'} -- a rebuilt board and the held one give "
        f"{'the same' if reused == rebuilt else 'DIFFERENT'} bytes on the same seed"
    )
    out.append("")
    out.extend(audible_cost_report())
    return out


def audible_cost_report(picks_sampled: int = 16) -> list[str]:
    """What one ``compute_view`` over audible's real board costs, and is the board reusable.

    Measured against the PINNED Green Hope board -- ``scripts/fixtures/qa-board-*.json``,
    3,304 entries -- so it is offline and reproducible, and so it is the board B2 will
    actually put in the seat rather than a stand-in.

    The loader lives in ``scripts/qa_board_fixture.py`` and is reached by path rather than
    imported as a package, because ``scripts/`` is not one. Nothing is written; the fixture
    is opened read-only.
    """
    import importlib.util

    out = ["  audible in the seat (what B2 adds, and what B3 must size against):"]
    loader_path = Path(__file__).resolve().parents[1] / "scripts" / "qa_board_fixture.py"
    fixture = loader_path.parent / "fixtures" / "qa-board-espn_green_hope.json"
    if not (loader_path.exists() and fixture.exists()):
        out.append(f"    UNRESOLVED: no pinned board at {fixture}; cost not measured")
        return out

    spec = importlib.util.spec_from_file_location("_qa_board_fixture", loader_path)
    if spec is None or spec.loader is None:  # pragma: no cover -- an unreadable script
        out.append(f"    UNRESOLVED: {loader_path} is not importable; cost not measured")
        return out
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from audible.config import load_league
    from audible.draft.live import Pick, compute_view

    config = load_league(Path(__file__).resolve().parents[1] / "leagues" / "espn_green_hope.toml")
    t0 = time.perf_counter()
    ab = module.load_board("espn_green_hope", fixture)
    t_load = time.perf_counter() - t0

    order = [e.player_id for e in ab.entries]
    picks = [
        Pick(pick_no=i, round=(i - 1) // config.num_teams + 1,
             draft_slot=slot_on_clock(i, config.num_teams), player_id=order[i - 1])
        for i in range(1, PICKS + 1)
    ]

    # Time compute_view at picks spread across the draft. The available pool shrinks as the
    # draft goes, so pick 1 is the MOST expensive and the last is the cheapest -- timing only
    # pick 1 would overstate a full draft by roughly the ratio between them.
    step = max(1, PICKS // picks_sampled)
    samples: list[float] = []
    for n in range(0, PICKS, step):
        t0 = time.perf_counter()
        compute_view(ab, picks[:n], 6, config, config.draft_rounds)
        samples.append(time.perf_counter() - t0)
    per_pick = st.mean(samples)

    out.append(f"    board entries:                    {len(ab.entries)}")
    out.append(f"    load the pinned board:            {t_load * 1000:8.1f} ms")
    out.append(
        f"    compute_view, mean over {len(samples)} picks:  {per_pick * 1000:8.1f} ms "
        f"(first {samples[0] * 1000:.1f}, last {samples[-1] * 1000:.1f})"
    )
    out.append(f"    x128 picks, one full draft:       {per_pick * PICKS * 1000:8.1f} ms")
    out.append(
        f"    a 1000-seed sweep would cost:     "
        f"{per_pick * PICKS * 1000 / 60:8.1f} min of ordering alone"
    )

    # Reuse, demonstrated rather than asserted: run the SAME board object through two
    # unrelated draft states and check the second is what it would have been on its own.
    a = compute_view(ab, picks[:40], 6, config, config.draft_rounds)
    _ = compute_view(ab, picks[:100], 6, config, config.draft_rounds)
    b = compute_view(ab, picks[:40], 6, config, config.draft_rounds)
    same = [e.entry.player_id for e in a.ranked[:50]] == [e.entry.player_id for e in b.ranked[:50]]
    out.append(
        f"    board reusable across seeds:      "
        f"{'yes' if same else 'NO'} -- 100 picks run through the same board object left the "
        f"40-pick view {'unchanged' if same else 'CHANGED'}"
    )
    out.append(
        "    so: build once per (league, season), share it across every seed. The board "
        "carries no draft state --"
    )
    out.append(
        "    DraftEntry and DraftBoard are frozen and build_board_from_lines takes no picks."
    )
    return out


if __name__ == "__main__":
    sys.exit(main())
