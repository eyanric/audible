# B11 — the loop against `transform - ffa_baseline`

One entry per iteration, fixed schema, so the progression
diffs in git. Predictions are committed BEFORE the run
that tests them; commit order is the timestamp.

The target holds the projection, the rulebook, the board,
the room and the seeds fixed and varies only replacement
depth, so a room bias is common-mode and cancels.

```
starting point, transform - ffa_baseline, prior lineup
  ffc_12   -66.7 [ -92.9, -40.5]  resolvable
  mfl_12   -68.8 [-114.5, -23.1]  resolvable
  mfl_8    -46.5 [ -80.9, -12.0]  resolvable, but that
           market's shuffle arm includes zero
```

---

## Iteration 0 — the measurement the loop starts from

Not an iteration; the table every prediction below is
made against. Depth means "how far down its own list at
that position the baseline sits".

```
              QB     RB     WR     TE     K    DEF
real        13.0   40.0   48.0   10.4   8.2   8.4
FFA         11.8   34.8   35.8   11.8   7.4   2.0
ours         8.0   52.0   35.0   17.0   8.0   8.0

ours - FFA  -3.8  +17.2   -0.8   +5.2  +0.6  +6.0
ours - real -5.0  +12.0  -13.0   +6.6  -0.2  -0.4
```

`real` is rostered inside 128 picks over the five
completed league-6012 drafts. `FFA` is recomputed from
its own `points`/`points_vor`, not read from a
docstring. `ours` is `rostered_counts` over the same
FFA-built pool the arms draft from.

MEASURED AND WORTH STATING: `ours` is IDENTICAL in all
three markets. `rostered_counts` reads the league config
and the projection pool and never the board, so the
depth under test is market-independent even though the
arm gap it produces is not.

Ranked by |ours - FFA|, which is what the target
compares against: RB 17.2, DEF 6.0, TE 5.2, QB 3.8,
K 0.6, WR 0.8.

TWO OF THOSE ARE NOT DEFECTS. On DEF we sit at 8.0
against a real 8.4 and FFA sits at 2.0; on K we sit at
8.0 against a real 8.2 and FFA at 7.4. We are closer to
the league than FFA is on both, so chasing FFA there
would be chasing its error. The positions where FFA is
genuinely closer to the completed drafts than we are:
RB (5.2 against our 12.0), TE (1.4 against 6.6) and
QB (1.2 against 5.0).

So the real target is RB, and QB and TE behind it.

---

## Iteration 1 — reproduce audible#73's change

PREDICTION COMMITTED BEFORE THE RUN.

### The change

`src/audible/value/replacement.py::rostered_counts`
selects which positions share the bench pool with
`_startable_slots(config, pos) >= 2`. In a 1-QB league
QB has one starting slot, so it is excluded and gets
starters only. Replace the slot test with a named set of
positions that are STREAMED and therefore get no bench,
which is what the slot count was standing in for.

This is audible#73's change, reproduced rather than
merged. Main's `replacement.py` is byte-identical to
that PR's base, so the comparison is clean.

### Mechanism, as a claim

audible#73 claimed the gain was QB being too shallow.
ITS OWN FOLLOW-UP REFUTED THAT: the QB move alone was
worth -6.18 by its counterfactual and +9.10 by the
reviewer's, not the +18.2 the change produced, and the
measured market depth of 13.0 scored WORST of five
depths swept.

So the claim under test here is the surviving one: the
bench pool is FIXED at 56 slots, and what moves the
number is the redistribution the pool forces out of
RB/WR/TE, not the QB share itself.

Computed depth after the change, arithmetic not a guess:

```
            QB    RB    WR    TE     K   DEF   |err FFA|
before     8.0  52.0  35.0  17.0   8.0   8.0      33.6
after     16.0  48.0  32.0  16.0   8.0   8.0      32.0
```

Note what that says: total depth error against FFA
barely moves, 33.6 to 32.0. RB improves by 4 and TE by
1, QB overshoots FFA by 4.2 and WR moves 3 the wrong
way. If the arm gap moves by anything like audible#73's
+18.2, then the arm gap is NOT a simple function of
total depth error, and RB's four units are worth far
more than WR's three -- which would be a fact about the
steepness of the curves, not about QB.

### Predicted effect

```
  ffc_12   -66.7 -> -48.5   (+18, reproducing #73)
  mfl_12   -68.8 -> -51     (+18)
  mfl_8    -46.5 -> -29     (+18)
```

The depth change is identical in all three markets, so
the effect should be similar in all three. If it appears
only in ffc_12 it is a market artifact, and that
cross-check is what audible#73 lacked.

Confidence: the ffc_12 figure is a reproduction of a
recorded measurement on identical code and should land
close. The two MFL figures are extrapolations from it
and could be wrong in size; the claim being tested is
the SIGN and the presence in all three.

### UNSTARTABLE_FACTOR, stated and deferred

`src/audible/draft/ordering.py:149-153` returns
`UNSTARTABLE_FACTOR = 0.05` for a second quarterback in
a 1-QB league, and `ordering.startable_slots` is a
deliberate mirror of the value engine's rule -- its
docstring says so. After this change the value engine
says two QBs a team are rostered while the ordering
still says the second is worth 5% of his score.

NOT RESOLVED THIS ITERATION, and the reason is that it
does not touch the target. `transform` and
`ffa_baseline` are both built by
`build_board_from_lines` -> `compute_vorp`, which reads
`replacement.py` and never `ordering.py`.
`effective_score` reaches only the `real` arm, which is
the cockpit's own path. Changing it would move `real`
and not the comparison under test, and it would be a
second change in one iteration. Logged for a later
cycle.

### Result

RAN. Depth moved exactly as the arithmetic predicted:
QB 8->16, RB 52->48, WR 35->32, TE 17->16, K and DEF
unchanged, in all three markets and all five seasons.

```
transform - ffa_baseline, prior lineup
  market   before  predicted   actual              moved
  ffc_12   -66.7    -48.5      -48.5 [-71.0,-26.1]  +18.2
  mfl_12   -68.8    -51.0      -40.3 [-61.2,-19.4]  +28.5
  mfl_8    -46.5    -29.0      -42.7 [-75.5, -9.9]   +3.8
```

PREDICTED VERSUS ACTUAL. ffc_12 landed on the recorded
value to the decimal, which is what a reproduction
should do. mfl_12 beat the prediction by 10.7 and mfl_8
missed it by 13.7. The SIGN held in all three, which was
the claim being tested; the SIZE did not, and the market
that matches the league's team count moved least.

### AGREEMENT: no, on both halves. The mechanism is
### refuted, and the improvement resolves in one market.

MECHANISM, REFUTED BY ITS OWN COUNTERFACTUAL. The claim
above was that the fixed bench pool forces a
redistribution out of RB/WR/TE and that this, not the QB
share, moves the number. Two illegal allocations isolate
the halves -- one moves QB 8->16 and HOLDS RB/WR/TE at
52/35/17 (over-spending the pool), the other keeps QB at
8 and takes the new 48/32/16 (under-spending it).
Paired on (season, seed), clustered, on ffc_12:

```
  after - before  (shipped)          +18.19 [ +6.11,+30.26]
  QB move alone                       +9.10 [ -7.83,+26.03]
  redistribution alone                -9.26 [-25.36, +6.84]
  after - cfB (adding the QB move)   +27.45 [ +6.58,+48.31]
  after - cfA (adding the redistrib.) +9.08 [ -5.59,+23.76]
```

THE REDISTRIBUTION ALONE IS NEGATIVE. The QB move is the
whole gain and is the only half that is resolvable when
added last. The claim was exactly backwards, and the
harness's own by-position attribution says the same in
every market -- QB +57.1 on ffc_12 with WR -23.1,
TE -10.0, K -10.3 and RB +0.8 giving most of it back.

audible#73's follow-up attributed -6.18 to one
construction and +9.10 to the other; +9.10 reproduces
and -6.18 does not. That figure was carried forward
uncritically into this log's own iteration-1 text and
into audible#73's, and it is withdrawn.

IMPROVEMENT, RESOLVABLE IN ONE MARKET OF THREE. Paired
on the same units rather than comparing two overlapping
intervals:

```
  ffc_12  +18.19 [ +6.11, +30.26]  5/5 seasons positive
  mfl_12  +28.51 [ -8.22, +65.24]  5/5 seasons positive
  mfl_8    +3.80 [-35.66, +43.26]  3/5, sign flips
```

Only ffc_12 excludes zero. And on mfl_8 the direction
reverses under the un-netted measure: the transform
arm's own points FELL by 3.28 while the opponent field
fell by 7.08, so the whole "improvement" there is the
seat denying the bots points rather than the seat
scoring more. On ffc_12 the seat's own points gain is
+14.47 [-1.80, +30.75], also not resolvable; 3.7 of the
headline +18.2 is the field.

### A CONTROL BROKE. The loop stops here.

Three committed gates go red, all three introduced by
this change and all three green again on revert
(sim/test_g_b4.py and sim/test_g_b6.py: 50 passed):

```
  test_g_b4.py
    ::test_the_b4_producers_are_actually_executed
    ::test_g0_the_live_projection_matches_committed
  test_g_b6.py
    ::test_the_qb_baseline_defect_is_reported
```

THE FIRST IS SEMANTIC AND IT IS THE ONE THAT MATTERS.
It asserts that `points_greedy` drafts MORE
quarterbacks than `audible_transform`, because
replacement level's first-order effect in a one-QB
league is to demote quarterbacks. After the change both
draft 3.0 and the transform carries 2.73 to 2.89 QBs a
team against a league that rosters 1.63. The gate is
not a stale pin; it is firing on a real regression.

The structural metrics agree, and the artifact puts them
first as the outcomes with known-correct directions:

```
  audible_transform      ffc          mfl12         mfl8
  wasted_roster_slots  1.05->1.96   1.03->1.97   1.07->2.11
  positional_surplus   5.93->6.22   6.00->6.15   6.01->6.22
  unfillable_byes      3.00->3.16   3.21->3.23   2.98->3.14
```

`wasted_roster_slots` is defined as surplus at a
position that can fill at most one starting slot -- D/ST,
K and QB in this league. It roughly DOUBLES.

### A note on the committed artifacts

`b11i1-{ffc,mfl12,mfl8}.json` are the iteration-1 runs.
They carry `run: b10-ffc` and so on in their own header,
because they were produced by running the b10 configs
with `--out` pointed at a new name so that the ONLY
difference from the committed b10 artifacts is the src
change. That makes them a clean paired comparison and it
makes their `run:` field wrong; both facts are stated
here rather than left for a reader to trip over. They
are kept because they are the evidence for a change that
is NOT shipped.

### Disposition: REVERTED, and audible#73 should not merge

The handoff's rule is that a fix which improves the gap
is kept even when the mechanism does not match. That
rule is about a mechanism mismatch, and this is not only
that: a control broke, and the only ways to ship it are
to weaken the gate (forbidden) or to ship a known
regression. So the src change is reverted and the loop
stops on the stop rule.

audible#73 is NOT superseded and NOT reproduced onto
this branch. It is MEASURED, and the measurement says it
should not merge as it stands: it buys a resolvable
+18.2 on one market by promoting quarterbacks past the
point the league drafts them, and it pays for that with
a doubled wasted-roster-slot count and a broken semantic
control that its own branch never ran.

### What survives, and what iteration 2 would have been

QB 8 IS TOO SHALLOW AND QB 16 IS TOO DEEP. The league
rosters 13.0 and FFA uses 11.8; audible#73 jumps the
baseline from one wrong side to the other and overshoots
by about as much as it was short. The measured next step
is an allocation that lands near 13 without overshooting,
and one is already computed:

```
  allocate the bench by STARTING-SLOT ELIGIBILITY
  (a config property) rather than by ASSIGNED STARTERS
  (a projection property, which the FLEX slot inflates
  for RB and compounds)

              QB    RB    WR    TE     K   DEF  |err real|
  shipped    8.0  52.0  35.0  17.0   8.0   8.0     37.2
  audible#73 16.0  48.0  32.0  16.0   8.0   8.0     33.2
  by slots   14.0  43.0  35.0  20.0   8.0   8.0     27.2
  real       13.0  40.0  48.0  10.4   8.2   8.4
```

It is closer to the league on QB (14 against 13.0) and
on RB (43 against 40.0), which is the largest single
error in the table, and it is a config-derived rule
rather than a named position list. It was NOT run: the
stop rule fired first, and running it would have been a
second change in a session whose first one broke a
control.

### Also found, not fixed

  * `ordering.py:94` documents itself as mirroring
    `value.replacement._startable_slots`, which
    audible#73 DELETES. Dangling reference in production
    code, on that branch.
  * `sim/ffa.py:675` still quotes our depth as
    "QB9, TE18, RB53, WR36". Measured today it is
    QB8/TE17/RB52/WR35. A wrong comment is a defect.
  * `replacement.py`'s NO_BENCH_DEPTH lists "DST" and
    "D/ST", which `LeagueConfig` validation rejects, so
    neither can ever appear in `config.positions`. They
    create false confidence about spelling coverage.
  * The live cockpit board moves a lot and the sim
    cannot see it: `seat.board_from_season` never calls
    `compute_vorp`, so `real` is byte-identical. Built
    from the 2026 lines under `espn_davis_drive`, the
    change moves Josh Allen from overall 28 to 14 and
    Joe Burrow from 108 to 63, and every skill player
    loses 3 to 8 VORP. Unmeasurable here by construction.
  * `hindsight_board` and `hindsight_total` DID move
    (they order on `vorp_rank`), so the ceiling moved by
    +31.5 / +25.2 / +17.0 and fraction-of-ceiling is not
    comparable across the two runs.
