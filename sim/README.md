# `sim/` — defect reproduction gates

**These gates were RED on purpose. Four are now green, and that is the deliverable changing
hands rather than the rules changing.**

Defects were found by a human noticing a bad recommendation mid-draft, across three drafts.
This package reproduces them offline, deterministically, from hand-built board and roster
states — so that fixes have something to turn green, and so a further defect of the same
shape cannot hide.

A harness that cannot detect the defects you already know about cannot detect one you do not.

## Running them

```
uv run python -m pytest sim -m slow
```

They are excluded from the default run two independent ways: `testpaths = ["tests"]` does not
reach this directory, and `addopts` carries `-m "not slow"`. The default run must stay fast —
it is what gates draft day. Adding a gate cannot forget the marker: `sim/conftest.py` applies
it to every collected item.

Dependencies live in the `sim` dependency group, separate from `dev` and therefore not
installed by `uv sync --no-dev` — what the Dockerfile runs. `sim/` is also in `.dockerignore`,
though the Dockerfile's explicit `COPY` list is the real protection.

## What each gate says

Every gate asserts the CORRECT behaviour. Each carries at least one CONTROL that passes on
both sides of its fix, so a red can never be blamed on a broken harness and a green can never
be blamed on a relaxed assertion.

**G-OCC** — GREEN since `audible#60`. With `IDP_FLEX` filled, occupancy is computed correctly:
the slot is absent from `unfilled_starting_slots` and every remaining linebacker reads
`fills_a_need: False`. `recommend` used to name two more linebackers anyway.

**G-NEED** — GREEN since `audible#60`, and the same root cause as G-OCC, which was the
finding. `recommend` sorted by `(not grab_now, vorp_rank, not fills_need)` and `vorp_rank` is
a **unique** integer, so the third key was never compared. Hold the board fixed and flip the
roster from thin-at-RB to thin-at-WR: the answer did not change.

**G-CALL** — GREEN since `audible#61`. The same class of defect on the OTHER surface, and the
one Eric actually reads. `recommend` is an MCP tool; the cockpit page renders `the_call`.
`audible#60` moved `recommend` to the composed `effective_score` scalar and left The Call
sorting by raw `vorp_rank`, because `server/state.py::_the_call` rebuilds its candidate rows
by hand and did not name the field. Need was never broken here and the top-12 slice always
held the right answer — measured, at slice position 2 — so neither of the two hypotheses on
offer was correct. What was missing is that `need` is a 2/1/0 bucket that ties at 0 for almost
everyone once the lineup is nearly full, and the ordering then fell through to board rank.

**G-BYE** — GREEN since `audible#61`, on a REBUILT fixture. The merged version gave its
"clean" alternative the same bye as three receivers and the tight end, so that candidate
landed on the roster's already-worst week and cost **9.0** against the collider's **5.0**. It
was asserting a defect, not detecting one. Rebuilt on the control from `tests/test_ordering.py`
where the mechanism discriminates: roster 14.0, shared bye +5.0, unshared bye +1.0.

**G-SURV — RETIRED, because it was wrong.** It asserted `any(grab_now)` at a wheel.
`tests/test_live.py::test_wheel_picks_have_a_one_pick_horizon` asserts the exact opposite
(`assert not any(c.grab_now for c in view.best_available)` at
`opponent_picks_until_horizon == 0`), and `tests/test_server.py` pins a "Two picks on the
clock" header derived from that same zero. Zero opponents between two consecutive picks is
CORRECT: nothing can be taken in between, so nothing is urgent. Making it green would require
redefining the survival horizon, which is wheel pairing. Seat 1 of 8 wheels at 16, 32, 48, 64,
80, 96 and 112, and **joint planning of a wheel pair is a real feature**, not a bug.

## What consumes each signal

```
survival()   -> display only (survival_pct, compare axes).
                grab_now, built from the same `if opponent_picks`
                guard, IS sort key term 1 in recommend. Silent at a
                wheel, and correctly so.
fills_need   -> display (fills_a_need) + the `forced` filter, and
                -need is The Call's LEADING key. It cannot
                discriminate inside a tier, which is what G-CALL is.
bye          -> priced into effective_score via
                ordering.marginal_bye_cost, and therefore into BOTH
                recommend's order and The Call's. Also displayed
                (bye, bye_week, bye_collisions, cmd_byes).
survives_by  -> The Call, via _urgency_tier, sort key term 2 --
                inside its own top-12 VORP slice.
effective_score -> the one scalar both surfaces order by.
                vorp * marginal_start_factor - bye penalty.
```

## Rules

- **Do not adjust a gate to change its colour.** If a gate is wrong, it is wrong, and that
  gets said out loud with evidence — which is what happened to G-SURV and to G-BYE's fixture.
- **No network, no historical data, no season replay.** Every state is built by hand. A defect
  you can only see by replaying a season is a defect you cannot put in CI.
- The gates import `src/audible/` and never modify it.
- Use `harness.current_pick_after` rather than a hand-counted pick number. Passing more player
  ids than the seat owns by `current_pick` silently leaves the surplus ON THE BOARD, and the
  gate then measures a roster it did not build.

## `probe.py`

Replay data inventory. Answers one question — can a season replay use audible's own *board*,
or only its *decision logic*? Run `uv run python -m sim.probe`. It builds no replay engine and
makes no network calls.

## `room.py` — B1, the opponent model

**The room resembles the real room on all six pre-registered statistics. Two of the six are
free of the fit, three are self-consistency and say so, and one is semi-free. Held out season
by season — refit on four, draft the fifth — 24 of 30 season-statistics are covered, and the
six misses are named rather than closed.**

```
uv run --extra nflverse python -m sim.room --cost
uv run --extra nflverse python -m sim.room --inject adp-only     # exits 1 when it fires
uv run pytest sim/test_g_room.py -m slow
```

### The finding: two clocks, not one sigma

The naive model — bots take the top 128 by ADP — spends **0–4** of 128 picks on K and D/ST.
The real league-6012 room spends **16–17**, every year. No sigma closes that: Fantasy Football
Calculator's first kicker sits at ADP rank 138–143 on a board 180–224 deep, so **zero**
kickers are inside the top 128 by ADP in any of the five seasons, and the real room took
eight every year.

The classifier is a count, not a correlation:

```
supply ratio = drafted in 128 picks / that position in the top 128 by ADP
  K   inf   (0 available across all five seasons, 41 drafted)   -> SCHEDULE
  DEF 3.82  (11 available, 42 drafted)                          -> SCHEDULE
  WR 0.93   RB 0.88   TE 0.87   QB 0.78                         -> board
```

Above 1.0 the room takes more of a position than the board holds, so those picks did not come
off the board. Worst scheduled season 2.25, best board season 1.00 — the cut has clearance and
1.0 is a meaning rather than a threshold.

**This replaced a correlation test, and the replacement is the review's finding.** The first
version split on `corr(ADP rank, actual pick)` — +0.87…+0.90 skill against +0.36…+0.39
specialist — and that is refuted two ways: the correlation is *invariant* to the 8/12 rescale
the whole two-clock story is about (both clocks are linear in rank), and the gap is range
restriction — inside the specialists' own rank-and-pick box, WR comes in at r = −0.11 and RB
at r = −0.50, **below** the specialists. The correlations are still reported, as diagnostics,
with that caveat attached.

So board positions get `rank + mu + N(0, sigma)` drawn once per player per draft; K and D/ST
get a per-seat target pick from a fitted `N(pick_mu, pick_sd)`; and a feasibility deadline
with zero parameters makes every seat finish able to field a legal lineup, which all forty
real team-seasons did.

### What each gate can and cannot say

| statistic | kind | why |
| --- | --- | --- |
| first QB round | free | the fit targets nothing like it |
| runs of 3+ | free | the fit targets nothing like it |
| K+DEF in 128 | semi | a consequence of the one-slot need test plus the deadline — *not* of the caps, which never bind |
| first K / first DEF round | fitted | comes straight out of the pick schedule |
| pick−ADP spread | fitted | this is what sigma is fitted to |

Only the **held-out** run is evidence for the fitted three. It comes back 24/30, and the
misses are the deliverable, not an embarrassment to smooth over.

### Six things this room does not do, left unfixed on purpose

Closing a held-out miss by adding a mechanism is what tuning a gate to pass looks like from
the inside. These are reported instead.

Found by the held-out check:

- **No second specialist.** K+DEF in 128 is exactly 16 in *every* synthetic draft; the real
  room took 17 in three seasons of five. Three of eighty real team-slot-seasons took a second.
- **No loose seasons.** Sigma is pooled across all five, so 2021 (board 224 rows, real spread
  27.5) and 2025 (221 rows, 26.8) come out near 20.8 like the rest. Board depth and real
  spread are rank-monotone across all five and a pooled sigma cannot express that.
- **2023's first defence** went in round 11 against a synthetic band of 12–14. The schedule is
  pooled like sigma. 2025 is the other season whose first K and first D/ST both came in round
  11, and it *is* covered.

Known independently:

- **No off-board picks.** 18 of 640 real picks (2.8%) were players FFC never listed — 7 K,
  4 DEF, 3 RB, 3 WR, 1 QB. Kickers are the plurality, not defences.
- **The spread gate is compared against a truncated target.** The real spread is computed over
  joined picks only. Give every off-board pick the most conservative rank possible and the
  real range becomes 22.5–37.7 rather than 20.6–27.5, and the synthetic 21.95 *fails*. That
  pass depends on the truncation.
- **The gate resolves the specialist schedule to about one round.** Shifting `pick_mu` by −8
  picks still passes all six; −12 and +8 do not. "Room resembles real" means "within about a
  round".

Two more that hold regardless and belong in every sim report: **no vintage preseason
projections exist for any season**, so this measures *ordering* and never the projections; and
bots fitted to ADP are not people — they do not stack, reach for their own players, or panic.

### Rules this file adds

- **Read-only against every cached input**, and it prints which root each came from on line 1.
  `resolve_input` prefers `data/sim-cache` and falls back *silently* to the cockpit's
  `data/cache`. That is deliberately **not** `probe.py`'s convention, which has no fallback —
  nothing here opens a file for writing, so the fallback is safe, but it is stated because
  reading one root while reporting another would not be.
- **No fitted parameter is a literal.** Every one is computed from the pinned files at run
  time, and `test_g1_sigma_*` and `test_g1_the_pick_schedule_*` drop a season to prove sigma
  and the schedule move. Three *structural* constants are literals and do change the output:
  `SUPPLY_RATIO_CUT`, `MIN_CELL`, `BUCKETS`.
- **`assert_pre_draft` runs before every draft.** Source allowlist *and* an `asof` strictly
  before that season's kickoff, derived (Thursday after Labor Day) rather than tabulated.
  Margins are 3–8 days, so it is not a formality.
- **Gates are mutation-tested.** A straight (non-snake) draft used to pass all 29 gates, and a
  room where 34.8% of seats could not field a lineup passed all six pre-registered statistics.
  Both now have gates. When you add a statistic, break the code and check it goes red.
