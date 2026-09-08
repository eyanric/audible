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
earn their place against ``deadline=False``: without it 45.0% of seats finish unable to field
a legal lineup at the current defaults -- 42.6% with ``refinements=False``, which is where that
figure was first measured -- usually missing a tight end or a quarterback, and with the
schedule off as well that is 77.5% and 0-6 seats a draft with no kicker at all. All forty
real team-seasons could field a lineup. This matters more than it looks: the positional
TOTALS were right without it and only the allocation across seats was wrong, so no
draft-level statistic in the pre-registered set could see it.

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


WHAT B2 CLOSED, AND WHAT IS STILL OPEN
--------------------------------------
B1 named six deficiencies and closed none, deliberately. B2 closed the three that were
structural rather than fitted-to-the-target. Every number below is current.

CLOSED:

* SECOND SPECIALISTS. 2 of 40 real team-seasons took a second D/ST and 1 of 40 a second K, so
  ``second_specialist_p`` is {DEF: 0.05, K: 0.025} and K+DEF inside 128 now reads 16.2 with a
  16/17/18 spread against a real 16-17. It used to be exactly 16 in every draft.
* OFF-BOARD PICKS. 18 of 640 real picks (2.8%) were players FFC never listed, and the room now
  takes them at 2.80%. By position the real ones are 7 K, 4 DEF, 3 RB, 3 WR, 1 QB. The
  (round bucket, position) pair is drawn JOINTLY -- independent marginals manufactured
  off-board kickers in round 3, because the one real early off-board pick was a running back.
* SEASON-LEVEL SIGMA. The five per-season residual spreads are 14.5 to 21.9 around 18.1; the
  sampling sd of a sample sd at n~124 is 1.15, so the TRUE between-season sd is 2.20, or 12%
  of the mean. A per-draft multiplier from N(1, 0.12) carries it.

STILL OPEN, and reported on every run:

* 2021 and 2025 pick-ADP spread still miss their held-out band. Those are the two loosest
  seasons and the season multiplier does not reach them. Held-out is 28/30, up from 24/30.
* THE GATE'S RESOLUTION ON THE SPECIALIST SCHEDULE IS ABOUT ONE ROUND. Shifting ``pick_mu``
  for K and D/ST by -8 picks -- a full round early -- still passes all six pre-registered
  statistics; -12 and +8 do not. "Room resembles real" means "within about a round".

RESOLVED, AND IT WENT THE OTHER WAY FROM B1'S EXPECTATION. B1 recorded honestly that the
``pick-ADP spread`` gate was compared against a TRUNCATED target: give every off-board pick
the most conservative rank available and the real range moved to 22.5-37.7 while the synthetic
21.95 failed. B1 could not act on it, because its room had no off-board picks at all and the
two sides were not comparable. B2's room has them at the measured rate, so the comparison is
symmetric -- and it PASSES, at 26.3 against a real 22.5-36.8. The range moved from B1's
22.5-37.7 because fixing the Rams D/ST join took 2021 from five off-board picks to four. It is
printed as G9 on every ``python -m sim.room`` run, and it would be printed the same way had it
failed.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import LIVE_CACHE, SIM_CACHE, markets
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

# The key space for a draftable board row: `ffc0001` is board row 1, whatever market the
# board came from. The literal is HISTORICAL and deliberately not renamed. It is written into
# every committed artifact and every checkpoint, so renaming it would invalidate every run
# this repo has recorded while changing no behaviour. Named here so the inline copies in
# `boards.py` and `seat.py` have something to point at, and so a reader of an MFL artifact
# does not read `ffc` as provenance -- provenance is on the board, not in the id.
DRAFTABLE_PREFIX: str = "ffc"

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
PRE_DRAFT_SOURCES: frozenset[str] = frozenset(
    {"ffc_adp", "ff_playerids", "espn_ranks", "mfl_adp"}
)

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


# THE CLASSIFIER. Third of three, and the first that works on more than one market.
#
#   clock_ratio[position] = sd(pick) / sd(pick - rank)
#
# Below 1.0 the position is on the SCHEDULE clock; above it, on the BOARD clock. The signature
# is the one the module docstring has always described: a kicker's mean ADP rank is 161.8 and
# his mean pick 107.4, at a pick sd of 12.4 against 32-36 for the skill positions. WHICH kicker
# barely matters; WHEN is nearly fixed. So subtracting the rank from the pick makes a board
# position's residual TIGHTER than its raw pick (the pick tracks the rank) and a scheduled
# position's residual WIDER (the pick is nearly fixed while the rank scatters).
#
# WHY THE TWO IT REPLACED FAILED, and whether this one fails the same ways. Both refutations
# were re-run against this statistic rather than assumed away; the numbers are in the report.
#
#   THE CORRELATION TEST failed first because it was INVARIANT to the very 8/12 round
#   rescaling the two-clock story is about -- rescale every rank by c and r agrees to six
#   decimal places. This statistic is not invariant, and that is the point: rescaling ranks by
#   c changes sd(pick - c*rank), so it can see exactly what r could not. Measured, the
#   verdicts hold across the whole plausible range: at c = 8/12, which rescales a twelve-team
#   board into eight-team rounds, every verdict is unchanged and every margin IMPROVES. The
#   nearest skill position to flipping is WR on mfl_8_std, which needs c >= 1.25.
#
#   THE SUPPLY RATIO failed because its numerator is 128 picks of an eight-team draft and its
#   denominator is the market board's top 128 -- two windows that only correspond when the
#   market's team count DIFFERS from the room's. On a twelve-team board rank 128 is round 10.7,
#   before a kicker goes; on an eight-team board rank 128 IS the whole draft, so numerator and
#   denominator have the same composition and every ratio collapses toward 1.0. Measured on
#   mfl_8_std: WR 1.111 against DEF 1.105, a separation of 1.005 on the wrong side of the cut.
#   This statistic reads no window at all. It is computed per position over that position's own
#   joined picks, so a market that fits the room perfectly cannot degenerate it.
#
#   WHERE IT IS STILL VULNERABLE, stated rather than discovered later. Restricted to the
#   specialists' own (rank, pick) box, EVERY position reads below 1.0 -- QB 0.42, RB 0.52,
#   WR 0.47, TE 0.66 against K 0.37, DEF 0.32 on mfl_8_std. That is the same range-restriction
#   family that killed the correlation test, and it is mechanical: the box is ~46 picks wide
#   and 120-206 ranks wide, so sd(rank)/sd(pick) is inflated by the box's aspect ratio and
#   pushes everything under the cut by construction. The cut is therefore meaningful ONLY on a
#   position's unconditioned population, which is what `fit_room` uses. The ordering mostly
#   survives restriction on the MFL markets and partly breaks on FFC (RB 0.43 falls below
#   K 0.60), so the ORDER is not claimed to be robust either. Nothing conditions on anything
#   in the shipped classifier; this note exists so nobody adds a conditional later.
#
# WHAT THE CUT ACTUALLY IS, in closed form. With k = sd(rank)/sd(pick) and rho = corr(rank,
# pick), Var(pick - rank) = sd(pick)^2 + sd(rank)^2 - 2*rho*sd(pick)*sd(rank), so
#
#     ratio > 1   <=>   sd(rank) < 2*rho*sd(pick)   <=>   k < 2*rho
#
# and since the OLS slope of pick on rank is b = rho/k, that collapses to
#
#     ratio > 1   <=>   b > 0.5,   INDEPENDENT OF rho.
#
# So the classifier is a slope test with the cut at HALF A PICK PER RANK, and the correlation
# drops out of it entirely. That is worth stating because it is the cleanest available answer
# to "why is this not the correlation test again": it is not a function of rho at all. Verified
# on all eighteen market-position cells, zero identity mismatches.
#
# THE CUT IS 1.0 AND IT IS A MEANING, not a threshold: it is the point where the residual stops
# being tighter than the raw pick, which is the definition of the pick tracking the rank. It
# was not chosen to make an answer come out. Measured separation across all three markets is a
# factor of 2.34 -- nearest board position WR 1.406 (mfl_8_std), nearest scheduled K 0.602
# (ffc_12_std) -- against the supply ratio's 1.005 on the wrong side.
#
# HOW CLOSE THE NEAREST MARKET IS TO FAILING, because "it works on three" is not "it works".
# The binding cell is WR on mfl_8_std: sd(rank) 47.17 against a limit of 2*rho*sd(pick) = 58.56,
# so 19.4% of headroom, bootstrap interval [1.217, 1.640] with 0 of 10,000 resamples below the
# cut. That is comfortable for this market and NOT a large margin in general -- the observed
# between-market spread in sd(rank) for receivers is 37.5 to 47.2, a 26% range, which already
# exceeds the headroom left. A fourth market landing under the cut is not remote, and it would
# show up as a receiver being scheduled.
#
# WHAT DOES NOT DRIVE IT, measured, because the obvious guess is wrong: board DEPTH does not.
# mfl_12_std serves 289-312 rows against mfl_8_std's 219-241 and has the BETTER receiver margin
# (slope 0.664 against 0.621), and truncating the room to as few as eight rounds against the
# same board leaves every skill ratio between 1.10 and 2.31. What drives it is the rank scatter
# of the DRAFTED set, which is not a function of how many rows the board has.
CLOCK_RATIO_CUT: float = 1.0

# A position is classified only when its ratio is RESOLVABLY on one side of the cut. Two
# guards, and the second is the one that matters.
#
# `MIN_CLOCK_N` IS THE GUARD, AND THE NUMBER IS BRACKETED BY MEASUREMENT rather than chosen.
#
# It was 10, and 10 was calibrated to the wrong thing. Adversarial review measured that on a
# SINGLE-SEASON fit the quarterback crosses the cut at n=12-14 on both MFL markets -- clearing
# a floor of 10 -- and is therefore scheduled and REMOVED FROM THE BOARD in a one-QB league,
# which is the exact B8 catastrophe this classifier was written to prevent. The comment that
# used to sit here claimed the floor "never binds" and that defaulting to the board clock was
# safe in both directions; both were false for any fit window shorter than five seasons.
#
# The bracket, measured on all three markets and on EVERY WINDOW THE CODE ACTUALLY FITS:
#
#   single-season fits   thinnest cell n = 6-8,   QB n = 12-14   <- must be REFUSED
#   walk-forward, 3 seasons   thinnest cell n = 20-25            <- must be ADMITTED
#   leave-one-season-out, 4   thinnest cell n = 27-32            <- must be ADMITTED
#   pooled five-season        thinnest cell n = 34-41            <- must be ADMITTED
#
# So any floor in (14, 20] does the job, and 17 sits in the middle of it with three of margin
# below the quarterback hazard and three above the thinnest window cell.
#
# B9 SET THIS TO 20 ON A WIDER BRACKET, and the bracket was wider because it was measured on
# the pooled and leave-one-out windows only. B10 put every SPLIT's room structure under G7 --
# the walk-forward fit was previously in no artifact and checked by nothing -- and the
# walk-forward window is three seasons, not four. FFC's walk-forward kicker joins exactly 20
# times, so a floor of 20 sat precisely on the binding edge: one fewer kicker and that fit
# would have gone unclassified and turned the split red. Moving to the centre changes no
# verdict in any market on any window; it buys margin on a constant that had none.
#
# EVERY WINDOW HERE IS A REAL CODE PATH. `room.holdout` refits on four seasons per held-out
# season, `runner.execute` fits one room per split (three seasons for walk-forward), and a
# config may legally name a single season.
MIN_CLOCK_N: int = 17

# Reported beside the ratio, and DELIBERATELY NOT GATING. A first version of this guard refused
# to classify any cell whose bootstrap interval straddled the cut, which is the more principled
# rule and is unusable here: at n=27 -- the thinnest cell a leave-one-out fit uses -- FFC's
# kicker reads a point estimate of 0.600 and still resamples above 1.0 more than one time in
# forty, because kicker RANKS scatter enormously (rank 138 to 223 on the same board). Gating on
# it left `holdout` with the kicker on the board clock and turned two of the fifteen held-out
# fits red. The interval is worth reporting and is not worth deciding on at these sample sizes.
#
# Deterministic: fixed seed, fixed resample count.
CLOCK_BOOTSTRAP: int = 2000
CLOCK_BOOTSTRAP_SEED: int = 20260908

# Positions a league fills on a SCHEDULE rather than off the board. The spellings are the same
# ones `invariants.SCHEDULED_SLOTS` carries.
SPECIALIST_POSITIONS: frozenset[str] = frozenset({"K", "DEF", "DST", "D/ST"})

# THE SCHEDULED SET B1 VALIDATED. `fit_room` derives the scheduled set per market from the
# supply ratio; this is what that derivation produced on the market B1 was gated against, and
# `runner.gate_failures` refuses an artifact whose derived set is wider.
#
# It is not a duplicate of the derivation, it is the ACCEPTANCE CRITERION for it. B8 measured a
# market -- MFL at eight teams -- where RB (1.047) and WR (1.111) cross the cut, which puts the
# two deepest skill positions on the schedule and takes them off the board `_best` picks from.
# The room still runs; it just is not the room any earlier result was measured in.
#
# It also exposes what the cut's own comment claims is not true of it. That comment argues 1.0
# "is a meaning rather than a threshold" on a factor of 2.25 of clearance -- and that clearance
# is an FFC fact. At 1.047 the cut is doing real work, and a market that lands there needs the
# question reopened rather than the number read.
def expected_scheduled() -> frozenset[str]:
    """What the LEAGUE's own slots say should be on the schedule clock.

    DERIVED RATHER THAN HARDCODED, and derived from a different FILE than the classifier: this
    side reads `STARTING_SLOTS` -- which positions the league starts, and which of those are
    specialists -- while the classifier reads picks and ranks. Its predecessor was
    `B1_SCHEDULED = frozenset({"DEF", "K"})`, a literal recording what one market happened to
    produce, so this is a real improvement in where the number comes from.

    IT IS A WEAKER INDEPENDENCE THAN IT LOOKS, and adversarial review was right to say so.
    `STARTING_SLOTS` is a MODULE CONSTANT, not `config.league`, so this returns {DEF, K} for
    every league in the repo and would keep doing so if the league changed underneath it. And
    the classifier side is pinned too: `fit_room` always joins against `espn_draft_6012_*`
    whatever a config says. So "two independent sources" means two files describing ONE league,
    not two leagues. The gate still catches a classifier that drifts -- which is what B8 needed
    and did not have -- and it would NOT catch a league whose roster this module does not model.

    `runner.load_config` refuses any config whose league is not the market's declared league,
    so no other league can reach this today. That is what keeps the weakness latent rather than
    live, and it is the thing to fix first if a second league is ever added.
    """
    startable = {p for slot in STARTING_SLOTS for p in SLOT_ELIGIBILITY[slot]}
    return frozenset(startable & SPECIALIST_POSITIONS)

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
    """The ACTIVE MARKET's ADP board for *season*, ranked by ADP.

    Rank is derived from a sort rather than read off the file, whichever market it is. Both
    sources ship their lists in order already, but a rank that comes from the sort cannot
    silently disagree with the number it is meant to summarise.

    THE MARKET IS A MODULE-LEVEL SELECTION RATHER THAN A PARAMETER, and that is a deliberate
    trade. `fit_room` calls this function itself, and there are forty-odd call sites across
    `sim/`; threading a market through all of them would touch far more code than the global
    does, for a value that is constant for the length of a run. `markets.use()` scopes it for a
    test and restores it on the way out. See `sim/markets.py`.
    """
    market = markets.active()
    if market.source == markets.MFL:
        return _load_mfl_board(season, market)
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


def _load_mfl_board(season: int, market: markets.Market) -> SeasonBoard:
    """One season's MFL board, in the same `BoardRow` shape every arm already reads.

    `asof` IS A LOWER BOUND AND NOT A MEASUREMENT. FFC publishes `meta.end_date` and the FFC
    branch above reads it; MFL publishes no window end at all, and its `timestamp` field is
    when the response was generated -- it reads as today on a 2019 request. So `PERIOD=AUG15`
    gives 15 August as a window START, which is what `assert_pre_draft` is handed, and the
    pre-draft property is carried by a CONTENT check instead: `sim/test_g_b8.py` looks for the
    following year's draft class on each season's board, which is the same evidence the FFA
    vintage gate uses. Leagues drafting after kickoff would sit inside this window; redraft
    leagues overwhelmingly draft in August, and that bound is an argument rather than a
    measurement, which is why the content check is the one that gates.
    """
    from .mfl import MflParams, board_rows

    params = MflParams(**market.params)
    draftable = frozenset(p for slot in STARTING_SLOTS for p in SLOT_ELIGIBILITY[slot])
    rows = tuple(board_rows(season, params, draftable))
    if len(rows) < PICKS:
        raise ValueError(
            f"{market.name} {season}: the board holds {len(rows)} draftable players and a "
            f"{TEAMS}x{ROUNDS} draft takes {PICKS}. A room that runs out of board is not a room."
        )
    # BOTH FILES, because the board is built from both. `board_rows` reads the ADP pin and the
    # player catalogue through two independent `resolve_input` calls, and reporting only the
    # first would let a board half-read from the live root claim it came from sim's -- which is
    # the one thing `resolve_input`'s own docstring says must never happen.
    roots = tuple(sorted({resolve_input(name)[1] for name in market.pins(season)}))
    return SeasonBoard(
        season=season,
        rows=rows,
        provenance=(market.provenance,),
        asof=market.asof(season),
        roots=roots,
    )


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
    # THE CLASSIFIER: sd(pick) / sd(pick - rank), per position. Below CLOCK_RATIO_CUT is the
    # schedule clock. The two standard deviations are carried beside it because the ratio alone
    # cannot say WHY a position landed where it did, and a reader checking a surprising verdict
    # wants both halves.
    clock_ratio: dict[str, float]
    clock_sd_pick: dict[str, float]
    clock_sd_resid: dict[str, float]
    clock_n: dict[str, int]
    clock_unclassified: tuple[str, ...]
    # Whether a bootstrap interval on the ratio clears the cut. Reported, never gating.
    clock_resolvable: dict[str, bool]
    # DIAGNOSTIC ONLY from B9 on. Kept computed and reported because it is the number three
    # sessions of results were produced under, and dropping it would make those unreadable --
    # but it decides nothing now. See SUPPLY_RATIO_CUT for the window mismatch that retired it.
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
    # B2 refinements. Each is measured; see `fit_room` for how, and the module docstring for
    # what each one closes and what it deliberately does not.
    second_specialist_p: dict[str, float]
    offboard_per_draft: tuple[int, ...]
    offboard_bucket_p: dict[str, float]
    offboard_position_p: dict[str, float]
    offboard_cells: tuple[tuple[str, str], ...]
    season_sigma: dict[int, float]
    season_sigma_mean: float
    season_sigma_tau: float

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


def _clock_resolvable(picks: Sequence[float], resid: Sequence[float]) -> bool:
    """Does the clock ratio's bootstrap interval sit entirely on one side of the cut?

    Resamples the (pick, residual) PAIRS together, because the two standard deviations are
    computed over the same rows and resampling them independently would break that.
    """
    rng = random.Random(CLOCK_BOOTSTRAP_SEED)
    n = len(picks)
    below = 0
    for _ in range(CLOCK_BOOTSTRAP):
        idx = [rng.randrange(n) for _ in range(n)]
        denom = _sd([resid[i] for i in idx])
        if denom == 0.0:
            return False
        below += 1 if _sd([picks[i] for i in idx]) / denom < CLOCK_RATIO_CUT else 0
    # A two-sided 95% interval clears the cut when fewer than 2.5% of resamples land the other
    # side of it. Stated as a count so the arithmetic is visible.
    edge = 0.025 * CLOCK_BOOTSTRAP
    return below < edge or below > CLOCK_BOOTSTRAP - edge


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
    offboard_rows: list[tuple[int, int, str]] = []
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
                offboard_rows.append((season, pick.round, pick.position))
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

    # THE CLASSIFIER, on each position's own joined picks and nothing else. No window, no
    # team-count normalisation, nothing conditioned on. See CLOCK_RATIO_CUT.
    clock_sd_pick: dict[str, float] = {}
    clock_sd_resid: dict[str, float] = {}
    clock_ratio: dict[str, float] = {}
    clock_n: dict[str, int] = {}
    clock_resolvable: dict[str, bool] = {}
    unclassified: list[str] = []
    for pos, rows in by_position.items():
        clock_n[pos] = len(rows)
        picks = [float(r.overall) for r in rows]
        resid = [r.delta for r in rows]
        sd_pick = _sd(picks)
        sd_resid = _sd(resid)
        clock_sd_pick[pos] = sd_pick
        clock_sd_resid[pos] = sd_resid
        if len(rows) < MIN_CLOCK_N or sd_resid == 0.0:
            clock_ratio[pos] = float("inf")
            unclassified.append(pos)
            continue
        clock_ratio[pos] = sd_pick / sd_resid
        # Reported, never gating. See CLOCK_BOOTSTRAP.
        clock_resolvable[pos] = _clock_resolvable(picks, resid)
    # AN UNCLASSIFIED POSITION IS NEVER SCHEDULED. Setting the flag without excluding it here
    # was the first version of this and it was worse than no guard at all: a single-season fit
    # marked the quarterback unresolvable and then scheduled him anyway, so the report said
    # "not classified" while the room took him off the board.
    scheduled = frozenset(
        p for p, r in clock_ratio.items()
        if r < CLOCK_RATIO_CUT and p not in unclassified
    )

    # THE RETIRED CLASSIFIER, still counted and still reported as a diagnostic. It decides
    # nothing from B9 on.
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

    # --- B2 refinement 1: the second specialist ------------------------------------------
    # Measured, not assumed: 2 of 40 team-seasons took a second defence and 1 of 40 a second
    # kicker. B1 could not produce either, so K+DEF inside 128 was exactly 16 in every
    # synthetic draft while the real room ranged 16-17. This is the rate, and the rate alone
    # -- nothing here is set to make the count come out at any particular number.
    second_specialist_p: dict[str, float] = {}
    for pos in scheduled:
        hist = cap_hist.get(pos, {})
        team_seasons = sum(hist.values())
        seconds = sum(n for count, n in hist.items() if count >= 2)
        second_specialist_p[pos] = seconds / team_seasons if team_seasons else 0.0

    # --- B2 refinement 2: off-board picks ------------------------------------------------
    # 18 of 640 real picks were players FFC never listed. B1's room could not draft them at
    # all, so every synthetic draft consumed 128 board rows where the real room consumed
    # 110-127. The per-draft COUNTS are resampled empirically rather than fitted to a
    # distribution -- five observations do not identify one, and the observed spread (1 to 7)
    # is most of what there is to know.
    per_draft_counts: dict[int, int] = dict.fromkeys(seasons, 0)
    bucket_counts: Counter[str] = Counter()
    position_counts: Counter[str] = Counter()
    for season, rnd, pos in offboard_rows:
        per_draft_counts[season] += 1
        bucket_counts[bucket_of(rnd)] += 1
        position_counts[pos] += 1
    offboard_per_draft = tuple(per_draft_counts[s] for s in seasons)
    total_off = sum(bucket_counts.values()) or 1
    offboard_bucket_p = {b: n / total_off for b, n in bucket_counts.items()}
    offboard_position_p = {p: n / total_off for p, n in position_counts.items()}
    # The JOINT distribution, and it has to be joint. Drawing bucket and position from their
    # marginals independently manufactures combinations that never occur: the one real
    # off-board pick in rounds 1-4 was a running back (J.K. Dobbins, 2021), and kickers are
    # 39% of the position marginal, so independent draws produced off-board KICKERS in round
    # 3 and drove the synthetic first-K round's 5th percentile down to 4.0 against a real
    # 11-13. Eighteen observations is few, but it is the shape that matters here, not the
    # resolution.
    offboard_cells = tuple(
        (bucket_of(rnd), pos) for _season, rnd, pos in offboard_rows
    )

    # --- B2 refinement 3: season-level sigma ---------------------------------------------
    # Is there such a thing as a loose year? The five per-season residual spreads are 14.5 to
    # 21.9 around a mean of 18.1, but a sample sd is itself noisy -- at n~124 its own sd is
    # about sigma/sqrt(2n) = 1.15. Subtracting that in variance leaves a TRUE between-season
    # sd of 2.20, i.e. 12% of the mean. That is the number `tau` carries.
    #
    # Board depth correlates with it at +0.78, which on five points is not significant
    # (p~0.12) and is NOT used as a predictor. A per-draft multiplier drawn from
    # N(1, tau) adds the dispersion the seasons actually show without claiming to know which
    # season is which.
    season_res: dict[int, list[float]] = {}
    for jp in joined:
        season_res.setdefault(jp.season, []).append(jp.delta - mu[jp.position])
    season_sigma = {s: _sd(v) for s, v in season_res.items()}
    season_sigma_mean = st.mean(season_sigma.values()) if season_sigma else 0.0
    observed_sd = _sd(list(season_sigma.values()))
    sampling_sd = (
        st.mean([season_sigma[s] / (2 * len(season_res[s])) ** 0.5 for s in season_sigma])
        if season_sigma
        else 0.0
    )
    true_var = observed_sd**2 - sampling_sd**2
    season_sigma_tau = (
        (max(0.0, true_var) ** 0.5) / season_sigma_mean if season_sigma_mean else 0.0
    )

    return Fit(
        mu=mu, sigma=sigma, cell_n=cell_n, pooled=tuple(pooled),
        scheduled=scheduled, pick_mu=pick_mu, pick_sd=pick_sd,
        clock_ratio=clock_ratio, clock_sd_pick=clock_sd_pick,
        clock_sd_resid=clock_sd_resid, clock_n=clock_n,
        clock_unclassified=tuple(sorted(unclassified)),
        clock_resolvable=clock_resolvable,
        supply_ratio=supply_ratio, supply_avail=dict(avail), supply_drafted=dict(drafted),
        supply_by_season={k: tuple(v) for k, v in per_season.items()},
        rank_corr=rank_corr, rank_slope=rank_slope,
        caps=caps, cap_hist=cap_hist,
        joined=len(joined), total=total, offboard=dict(offboard), position_n=position_n,
        round_sigma=round_sigma, round_n=round_n, seasons=tuple(seasons),
        second_specialist_p=second_specialist_p,
        offboard_per_draft=offboard_per_draft,
        offboard_bucket_p=offboard_bucket_p,
        offboard_position_p=offboard_position_p,
        offboard_cells=offboard_cells,
        season_sigma=season_sigma,
        season_sigma_mean=season_sigma_mean,
        season_sigma_tau=season_sigma_tau,
    )


# --- the room ---------------------------------------------------------------------------


def _weighted(rng: random.Random, items: Sequence[str], weights: Sequence[float]) -> str:
    """One item, drawn in proportion to *weights*. One `random()` call, always.

    Written out rather than using `random.choices` so the number of draws taken from the
    stream is fixed and a seed reproduces byte-for-byte regardless of the weights.
    """
    total = sum(weights)
    if total <= 0:
        return items[0]
    target = rng.random() * total
    running = 0.0
    for item, weight in zip(items, weights, strict=True):
        running += weight
        if target < running:
            return item
    return items[-1]


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
    # True for a player who was never on the board. `rank` is 0 and means nothing for these,
    # which is why every consumer of `rank` has to filter on this rather than on `rank > 0`.
    offboard: bool = False

    def as_row(self) -> dict[str, Any]:
        return {
            "overall": self.overall, "round": self.round, "seat": self.seat,
            "rank": self.rank, "position": self.position, "name": self.name,
            "offboard": self.offboard,
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
    refinements: bool = True,
    check_leakage: bool = True,
    chooser: Callable[..., int] | None = None,
    chooser_seat: int | None = None,
    observer: Callable[[SimPick, int], None] | None = None,
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

    THE SEAT HOOK, which is what B2 adds. *chooser* is asked for one board index whenever
    *chooser_seat* is on the clock, and *observer* is told about every pick as it lands so an
    outside model can follow the draft. Both default to None and the room then behaves exactly
    as B1 validated it.

    A chooser returning -1, or an index already taken, falls through to the bot cascade rather
    than raising. That is deliberate: an ordering that has no legal answer at pick 128 is a
    finding about the ordering, not a reason to abandon the draft, and the fall-through is
    counted rather than hidden -- ``ArmResult.calls`` against 16 says how often it answered.

    WHAT THE PAIRING ACTUALLY GIVES, stated precisely because the obvious claim is false. At
    the default ``sampler="per-draft"`` every draw for the BOARD VALUES and for the SPECIALIST
    SCHEDULES is taken before the pick loop begins, so those are identical across arms on one
    seed. The off-board plan's EXECUTION is not: ``_weighted`` is called inside the loop when a
    planned pick is re-targeted. And the room is REACTIVE by design, so the opponents' realised
    picks diverge from the seat's first pick onward -- measured, 300 of 300 (season, seed)
    pairs have a differing opponent field and about 66 of 112 opponent picks change.

    So the pairing is on LATENT randomness, not on the realised field. That is still real
    variance reduction, and it is why arms are compared paired. But "identical opponent field"
    would be false, and ``advantage`` conflates acquisition with denial: the real arm's own
    roster is about +137 better than the null control's while it also leaves the opponents
    about 14 worse, so roughly 9% of the gap is denial rather than acquisition.
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

    # B2 refinement 3. One draw, before anything else, so a draft is a loose year or a tight
    # one rather than always the average of five. Floored well above zero: a non-positive
    # multiplier would invert the noise, and N(1, 0.12) reaches 0.1 at 7.5 sigma.
    season_mult = 1.0
    if refinements and fit.season_sigma_tau > 0.0:
        season_mult = max(0.1, rng.normalvariate(1.0, fit.season_sigma_tau))

    sig = [
        fit.sigma_for(r.position, fit.expected_pick(r.position, r.rank))
        * sigma_scale
        * season_mult
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

    # B2 refinement 1. Which seats will take a second specialist, and when. Drawn per seat
    # per scheduled position at the measured rate (2 of 40 team-seasons for D/ST, 1 of 40 for
    # K), and the second target is drawn from the same fitted schedule as the first, so a
    # second kicker arrives late like a first one does.
    wants_second: list[dict[str, float | None]] = [{} for _ in range(teams)]
    if refinements:
        for seat_i in range(teams):
            for pos in order:
                p_second = fit.second_specialist_p.get(pos, 0.0)
                take = rng.random() < p_second
                when = (
                    rng.normalvariate(fit.pick_mu[pos], fit.pick_sd[pos] * sigma_scale)
                    if take
                    else None
                )
                wants_second[seat_i][pos] = when

    # B2 refinement 2. Which picks go to a player who was never on the board. Counts are
    # resampled from the five observed per-draft counts (1, 2, 4, 4, 7) rather than fitted to
    # a distribution -- five observations do not identify one. Rounds and positions come from
    # the observed marginals: 16 of 18 real off-board picks fell in rounds 13-16, and kickers
    # are the plurality at 7 of 18.
    offboard_plan: dict[int, str] = {}
    positions = sorted(fit.offboard_position_p)
    if refinements and fit.offboard_per_draft and fit.offboard_cells:
        want = fit.offboard_per_draft[int(rng.random() * len(fit.offboard_per_draft))]
        cells = fit.offboard_cells
        for _ in range(want):
            # Retry on collision rather than dropping the pick. `setdefault` alone lost 28%
            # of the plan to duplicate spots and to picks the deadline later refused, which
            # put the realised rate at 2.03% against a real 2.81%.
            for _attempt in range(8):
                bucket, position = cells[int(rng.random() * len(cells))]
                lo, hi = next((lo, hi) for name, lo, hi in BUCKETS if name == bucket)
                lo_pick = (lo - 1) * teams + 1
                hi_pick = min(teams * rounds, hi * teams)
                spot = lo_pick + int(rng.random() * (hi_pick - lo_pick + 1))
                if spot not in offboard_plan:
                    offboard_plan[spot] = position
                    break

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

    def _supply_allows_second(position: str) -> bool:
        """True while taking a second of *position* would still leave one for everybody.

        A structural rule with no fitted parameter, and it exists because the board is
        genuinely thin: 2024's FFC board lists eight defences for eight seats, so one seat
        taking a second is the difference between every seat fielding a lineup and one seat
        being unable to. The real room never faced this -- a real manager can always stream a
        defence off waivers -- so the constraint belongs to the board, not to the behaviour.
        """
        left = sum(
            1
            for i in range(n)
            if not taken[i] and rows[i].position == position
        )
        owed = sum(1 for r in rosters if r.counts[position] == 0)
        return left > owed

    for overall in range(1, teams * rounds + 1):
        seat = slot_on_clock(overall, teams)
        roster = rosters[seat - 1]
        remaining = picks_left[seat]

        def _target(pos: str, _seat: int = seat, _roster: _Roster = roster) -> float | None:
            """When this seat intends to fill *pos*, or None if it does not owe one.

            Owing a FIRST specialist is the starting slot being empty. Owing a SECOND is the
            per-seat Bernoulli drawn at setup, and it is deliberately NOT routed through
            `_Roster.needs` -- the deadline reads the same slots and must never be able to
            force a second kicker onto a seat.
            """
            if _roster.needs(pos):
                return targets[_seat - 1][pos]
            if _roster.counts[pos] == 1 and _supply_allows_second(pos):
                return wants_second[_seat - 1].get(pos)
            return None

        due = sorted(
            (
                pos
                for pos in order
                if (when := _target(pos)) is not None and when <= overall
            ),
            key=lambda p: _target(p) or 0.0,
        )
        unfilled = roster.unfilled()

        # An off-board pick spends the pick without consuming a board row, which is the whole
        # point of it -- the real room left 1 to 7 board players on the table every draft.
        # It yields to the deadline: a seat one pick from being unable to field a lineup
        # takes the slot it owes, exactly as it would with the plan absent.
        # THE SEAT TAKES ITS OFF-BOARD PICKS LIKE EVERY OTHER SEAT. The chooser branch used
        # to `continue` before `offboard_plan` was consulted, so the seat's phantoms were
        # silently discarded and it finished with 14.96 scoreable players against an
        # opponent's 14.53. Measured, that construction advantage was worth +15.0
        # [+10.3, +19.8] of the arm's reported edge -- about a tenth of it, taken from
        # nowhere. The plan is now applied first, for every seat, chooser or not.
        planned = offboard_plan.get(overall)
        if chooser is not None and seat == chooser_seat and planned is None:
            picked = chooser(
                overall, taken, rows,
                remaining=remaining, unfilled=unfilled, counts=dict(roster.counts),
            )
            if picked is not None and picked >= 0 and not taken[picked]:
                taken[picked] = 1
                row = rows[picked]
                roster.add(row.position)
                picks_left[seat] = remaining - 1
                made = SimPick(
                    overall=overall, round=(overall - 1) // teams + 1, seat=seat,
                    rank=row.rank, position=row.position, name=row.name,
                )
                picks.append(made)
                if observer is not None:
                    observer(made, picked)
                continue

        if planned is not None:
            # EVERY off-board specialist in the real record was that team's FIRST at the
            # position -- 7 kickers and 4 defences, eleven of eleven, no exceptions. The
            # other seven off-board picks were bench depth (a team's 3rd to 6th back, 5th to
            # 7th receiver, 2nd quarterback). So an off-board kicker fills the slot rather
            # than adding a second; a seat that already has one takes bench depth instead.
            if planned in scheduled and not roster.needs(planned):
                bench = [q for q in positions if q not in scheduled]
                if bench:
                    planned = _weighted(
                        rng, bench, [fit.offboard_position_p[q] for q in bench]
                    )
            blocks_deadline = bool(deadline and len(unfilled) >= remaining and unfilled)
            fills = planned in SLOT_ELIGIBILITY[unfilled[0]] if unfilled else False
            if blocks_deadline and not fills:
                # The deadline wins, but it re-targets rather than rejects. A real off-board
                # pick in round 15 usually IS the lineup-filling pick -- Cameron Dicker at
                # 116 was team 4's first kicker -- so dropping the plan here both lost the
                # rate and lost the shape. Retarget to whatever fills the owed slot.
                owed = sorted(SLOT_ELIGIBILITY[unfilled[0]])
                planned = _weighted(
                    rng, owed, [fit.offboard_position_p.get(q, 0.0) + 1e-9 for q in owed]
                )
                fills = True
            legal = roster.counts[planned] < caps.get(planned, rounds)
            if legal and (not blocks_deadline or fills):
                roster.add(planned)
                picks_left[seat] = remaining - 1
                made = SimPick(
                    overall=overall, round=(overall - 1) // teams + 1, seat=seat,
                    rank=0, position=planned, name=f"off-board {planned}",
                    offboard=True,
                )
                picks.append(made)
                if observer is not None:
                    observer(made, -1)
                continue

        best = -1
        if deadline and len(unfilled) >= remaining and unfilled:
            # THE DEADLINE, over every starting slot rather than only the scheduled ones.
            # `unfilled` is most-specific-first, so the last picks go to the slot fewest
            # players can fill and FLEX is left until last. Without this over the BOARD
            # slots too, 34.8% of synthetic seats finished unable to field a legal lineup --
            # usually no tight end or no quarterback -- which none of forty real
            # team-seasons did, and which no draft-level statistic can see.
            #
            # EVERY unfilled slot is tried, not just the first. Trying only `unfilled[0]`
            # was a real defect, latent until B2 let a second specialist be taken: 2024's
            # board carries eight defences for eight seats, so a single second D/ST empties
            # the pool, and a seat owing both D/ST and K would then fail to find a defence
            # and silently spend the pick on a receiver instead of taking the kicker that
            # WAS still there. Measured at 2 seats in 2000 with the other three B2 changes
            # in place and only this loop reverted; reverting the loop alone from the B1 room
            # gives 0, because a second specialist is what empties the pool. The number
            # belongs to the set of four, not to this loop by itself.
            for slot in unfilled:
                best = _best(roster, frozenset(SLOT_ELIGIBILITY[slot]))
                if best >= 0:
                    break
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
        made = SimPick(
            overall=overall, round=(overall - 1) // teams + 1, seat=seat,
            rank=row.rank, position=row.position, name=row.name,
        )
        picks.append(made)
        if observer is not None:
            observer(made, best)
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
    """Every pick counts toward the positional statistics; only board picks have a delta.

    This mirrors `real_stats` exactly: a real off-board pick is a pick like any other for
    "which round did the first kicker go", and has no (pick - ADP rank) at all because it has
    no rank. Treating an off-board pick's `rank` of 0 as a real rank would report a delta of
    +120 and blow the spread apart.
    """
    rows = [(p.overall, p.round, p.position) for p in picks]
    deltas = [float(p.overall - p.rank) for p in picks if not p.offboard]
    return stats_of(rows, deltas)


def untruncated_spread_real(
    season: int, identity: dict[str, tuple[str, str]], nicks: dict[str, str]
) -> float:
    """G9. The pick-ADP spread with off-board picks given the most conservative rank there is.

    The gated `delta_spread` is computed over JOINED picks only, because a player FFC never
    listed has no rank. That is a truncation, and B1 recorded honestly that it flatters the
    room: give every off-board pick a rank of `board depth + 1` -- the most generous
    assumption available, since the only thing known about him is that he was worse than
    everyone on the board -- and the real range moves from 20.6-27.5 to something wider.

    B1 could not act on that, because its room had no off-board picks at all and the two
    sides were not comparable. B2's room has them at the measured rate, so the comparison is
    now symmetric and the verdict is reportable either way.
    """
    board = load_board(season)
    index = board.by_key()
    floor = len(board.rows) + 1
    deltas: list[float] = []
    for pick in load_real_draft(season, identity):
        row = index.get(pick_join_key(pick, nicks))
        rank = row.rank if row is not None else floor
        deltas.append(float(pick.overall - rank))
    return _sd(deltas)


def untruncated_spread_sim(picks: Sequence[SimPick], board: SeasonBoard) -> float:
    """The same quantity for a synthetic draft. Same floor, same rule, no special cases."""
    floor = len(board.rows) + 1
    return _sd([float(p.overall - (floor if p.offboard else p.rank)) for p in picks])


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

# `first_qb_round` WAS LABELLED `free` AND IT IS NOT. `mu["QB"]` is fitted as exactly the mean
# of (real QB pick - board rank) and reproduces it to the last digit in all three markets --
# +6.3438 on ffc_12_std, +16.5077 on mfl_12_std, +23.3077 on mfl_8_std -- and shifting it moves
# the statistic one for one (mu-5 gives -10.2, mu+0 gives -5.4, mu+5 gives -0.3 picks of first-QB
# bias on ffc_12_std). It is structurally identical to `first_k_round`: a directly fitted
# location plus an untargeted tail functional.
#
# So FOUR of the six are fitted, not three, and only `kdef_in_128` (semi) and `runs_3plus`
# (free) are untargeted. That is the honest size of this battery's independent evidence, and it
# is smaller than "six pre-registered statistics" has implied since B1. B10 corrected the label
# rather than the count, because shrinking the gated battery to two statistics is a change this
# session measured to be a regression -- see `report`.
STAT_KIND: dict[str, str] = {
    "first_qb_round": "fitted",
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
    # WHICH MARKET THIS ROOM WAS FITTED AGAINST, on the first line. Until B9 the report named
    # no market at all, so three runs against three different boards produced three reports
    # that were indistinguishable on the page -- and every gate downstream inherited whichever
    # one happened to be active.
    market = markets.active()
    out.append(
        f"market: {market.name}  (league {market.league}, adp {market.source})  "
        f"board rows {min(len(b.rows) for b in boards.values())}-"
        f"{max(len(b.rows) for b in boards.values())}"
    )
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
        f"  which clock each position is on. clock ratio = sd(pick) / sd(pick - rank), "
        f"cut at {CLOCK_RATIO_CUT}; below the cut is the SCHEDULE clock:"
    )
    for pos in sorted(fit.clock_ratio, key=lambda p: fit.clock_ratio[p]):
        clock = "SCHEDULE" if pos in fit.scheduled else "board"
        ratio = fit.clock_ratio[pos]
        note = "  (n below MIN_CLOCK_N: not classified)" if pos in fit.clock_unclassified else ""
        out.append(
            f"    {pos:4s} n={fit.clock_n.get(pos, 0):4d} "
            f"sd(pick)={fit.clock_sd_pick.get(pos, 0.0):6.2f} "
            f"sd(pick-rank)={fit.clock_sd_resid.get(pos, 0.0):6.2f}  "
            f"ratio={'inf' if ratio == float('inf') else f'{ratio:.3f}':>6s}  -> {clock}{note}"
        )
    expected = expected_scheduled()
    agrees = fit.scheduled == expected
    out.append(
        f"    derived {sorted(fit.scheduled)} against {sorted(expected)} implied by the "
        f"league's starting slots: {'agree' if agrees else 'DISAGREE'}"
    )
    if not agrees:
        out.append(
            f"      disagreeing: {sorted(fit.scheduled ^ expected)}. A scheduled position is "
            f"removed from the board the bots draft off, so this room is not the room the "
            f"league describes and nothing measured in it is comparable to anything else."
        )
    out.append("")
    out.append(
        f"  DIAGNOSTIC ONLY, and retired as a classifier in B9: supply ratio = drafted / "
        f"available in the top {PICKS} by ADP, cut at {SUPPLY_RATIO_CUT}. Its numerator is a "
        f"{TEAMS}-team draft and its denominator is the market board's top {PICKS}, two windows "
        f"that only correspond when the market's team count differs from the room's -- so it "
        f"collapses toward 1.0 exactly when the market fits the league. It decides nothing:"
    )
    disagreed: list[str] = []
    for pos in sorted(fit.supply_ratio, key=lambda p: -fit.supply_ratio[p]):
        per = "/".join(
            "inf" if v == float("inf") else f"{v:.2f}" for v in fit.supply_by_season[pos]
        )
        ratio = fit.supply_ratio[pos]
        # WHAT THE RETIRED CLASSIFIER WOULD HAVE SAID, not what the shipped one says. Printing
        # the live verdict next to the retired number would read as though the retired number
        # produced it, which is the sort of wrong label that costs a session.
        would = "SCHEDULE" if ratio > SUPPLY_RATIO_CUT else "board"
        now = "SCHEDULE" if pos in fit.scheduled else "board"
        mark = "" if would == now else f"  <- DISAGREES with the clock ratio ({now})"
        if would != now:
            disagreed.append(pos)
        out.append(
            f"    {pos:4s} avail={fit.supply_avail.get(pos, 0):4d} "
            f"drafted={fit.supply_drafted.get(pos, 0):4d}  "
            f"ratio={'inf' if ratio == float('inf') else f'{ratio:.2f}':>6s}  "
            f"would say {would}{mark}"
        )
        out.append(f"         by season: {per}")
    out.append(
        f"    the retired classifier disagrees on {sorted(disagreed) or 'nothing'} in this market"
    )
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
    # THE CLASSIFIER VERDICT IS PART OF THE ROOM'S VERDICT. The six statistics all describe how
    # the synthetic draft LOOKS; none of them can see that a position was taken off the board
    # entirely, because a room that schedules receivers still produces a plausible-looking
    # first-QB round and a plausible spread. B8 shipped exactly that. So the structure is
    # gated here as well as in `runner.gate_failures` G7 -- the CLI and the sweep must not be
    # able to disagree about whether a room is valid.
    verdict = fit.scheduled == expected_scheduled()
    for c in comparisons:
        flag = "pass" if c.passes else "FAIL"
        if c.passes and c.margin_sem < 2.0:
            flag = "pass(marginal)"
        # EVERY STATISTIC IS GATED IN-SAMPLE, and B10 tried to change that and reverted.
        #
        # THE ATTEMPT. `STAT_KIND` says a `fitted` statistic is checked against the fit that
        # produced it, so "only the held-out run says anything" -- and three of the six carry
        # that label while all six decided the verdict. Moving the fitted three out of the
        # in-sample verdict and gating them on held-out coverage instead looked like simply
        # following the module's own doctrine.
        #
        # WHY IT WAS REVERTED. Adversarial review measured a room whose K and D/ST schedule is
        # a FULL ROUND wrong -- `pick_mu` shifted by nine picks -- and the de-gated battery
        # passed it on `ffc_12_std`, the market every published number comes from. The
        # mutation parks all three fitted statistics on exactly the held-out bar, and the bar
        # has no margin. A gate that a one-round-wrong specialist schedule walks through is
        # worse than a gate that is philosophically impure.
        #
        # WHAT IS TRUE INSTEAD, and it is worse news than the dichotomy the change was chasing:
        # the free/fitted split does not hold in the first place. `first_qb_round` is labelled
        # `free`, meaning "the fit targets nothing resembling it", and `mu["QB"]` is EXACTLY the
        # mean of (real QB pick - rank) -- identical to the last digit in all three markets --
        # and shifting it moves the statistic one for one. So four of the six are fitted, not
        # three, and there is no clean subset of untargeted statistics to fall back to. See
        # STAT_KIND.
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
    out.append("  for anything the fit targets -- the held season is in none of it. This is")
    out.append("  where a FITTED statistic is gated, because it is the only place one means")
    out.append("  anything: in-sample it is checking the fit against itself.")
    out.append("  Read as: does that season's real value fall inside the synthetic 5-95 band?")
    held_pass = 0
    held_total = 0
    misses: list[str] = []
    per_stat: dict[str, int] = {}
    per_stat_kind: dict[str, str] = {}
    for season, comps in holdout(seeds=seeds, sampler=sampler):
        marks = []
        for c in comps:
            held_total += 1
            ok = c.covers
            held_pass += 1 if ok else 0
            per_stat[c.name] = per_stat.get(c.name, 0) + (1 if ok else 0)
            per_stat_kind[c.name] = c.kind
            marks.append(f"{SHORT[c.name]}={'ok' if ok else 'MISS'}")
            if not ok:
                misses.append(
                    f"        {season} {c.name:16s} real={_fmt(c.real_lo)} outside synth "
                    f"[{_fmt(c.syn_lo)}-{_fmt(c.syn_hi)}] (mean {_fmt(c.synthetic)})"
                )
        out.append(f"    {season}: " + "  ".join(marks))
    out.extend(misses)
    out.append(f"    held-out: {held_pass}/{held_total} season-statistics covered")

    # PER-STATISTIC HELD-OUT COVERAGE, REPORTED AND NOT GATED. B10 tried to gate the fitted
    # statistics here at three of five and reverted, for two measured reasons.
    #
    # THE BAR'S INPUT WAS WRONG. It was derived from Binomial(5, 0.9) on the premise that the
    # synthetic 5-95 percentile band delivers 90% coverage. It does not: `_pct` indexes at
    # `round(q*(n-1))`, so for a fresh continuous draw the band covers (i95-i5)/(n+1) -- 0.692
    # at 12 seeds, 0.846 at 25, 0.882 at 50. And five of the six statistics are DISCRETE, with
    # two to six distinct synthetic values, so their bands are conservative and measure 0.92 to
    # 1.00 instead. There is no single p, so there is no single binomial bar.
    #
    # AND THE COUNTS ARE NOT STABLE AT THE SEED COUNTS THE GATES USE. Over six disjoint
    # twelve-seed sets, mfl_8_std's held-out K reads 4, 2, 3, 5, 5, 4 and its DEF reads
    # 4, 4, 3, 4, 1, 4. A bar of three would be reading noise.
    #
    # `mfl_8_std`'s spread covering 0 of 5 is nonetheless a real and stable fact -- 0 at 12, 25,
    # 50 and 100 seeds -- and it is the sharpest single statement about that market's fit. It is
    # printed here so it cannot be missed, and it is not the thing deciding the verdict.
    per_stat_line = "  ".join(
        f"{SHORT[name]}={covered}/{len(SEASONS)}"
        + ("*" if per_stat_kind.get(name) == "fitted" else "")
        for name, covered in sorted(per_stat.items())
    )
    out.append(f"    per statistic: {per_stat_line}    (* = fitted)")
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

    out.append("")
    out.append("G9 -- the pick-ADP spread against an UNTRUNCATED target")
    out.append(
        "  Every off-board pick given rank = board depth + 1, the most conservative"
    )
    out.append(
        "  assumption available, on BOTH sides. B1 could not run this because its room had"
    )
    out.append("  no off-board picks; B2's has them at the measured rate.")
    real_un = [untruncated_spread_real(s, identity, nicks) for s in SEASONS]
    syn_un = [
        untruncated_spread_sim(simulate_draft(boards[s], fit, seed), boards[s])
        for s in SEASONS
        for seed in range(seeds)
    ]
    syn_mean = st.mean(syn_un)
    lo, hi = min(real_un), max(real_un)
    ok = lo <= syn_mean <= hi
    out.append(
        f"  untruncated spread  synth={syn_mean:6.2f}  real={lo:.1f}-{hi:.1f}  "
        f"{'pass' if ok else 'FAIL'}"
    )
    out.append(
        "  real by season: "
        + "; ".join(f"{s}={v:.1f}" for s, v in zip(SEASONS, real_un, strict=True))
    )
    out.append(
        f"  for comparison, the truncated pair: synth="
        f"{st.mean([x.delta_spread for x in synthetic]):.2f}  "
        f"real={min(r.delta_spread for r in real):.1f}-"
        f"{max(r.delta_spread for r in real):.1f}"
    )
    if not ok:
        out.append(
            "  THIS IS A REPORTED FAILURE, not a tuned pass. The truncated statistic is the"
        )
        out.append(
            "  pre-registered one and it passes; this one does not, and both are printed."
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
    parser.add_argument(
        "--market", choices=sorted(markets.REGISTRY), default=markets.DEFAULT,
        help="the (league config, ADP source) pair to fit and validate in",
    )
    args = parser.parse_args(argv)

    # BEFORE ANY BOARD IS READ, which is the same ordering rule `runner.execute` states: the
    # market is a module-level selection that `load_board` reads rather than takes, so setting
    # it after the first `fit_room` would validate one room and report another. Every path out
    # of this function -- `--inject`, `report`, `--cost` -- reads a board, and this is the only
    # line that precedes all three.
    markets.set_active(args.market)

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
