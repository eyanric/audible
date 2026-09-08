# B12 — the loop, continued

One entry per iteration, kept or reverted, fixed schema.
Predictions are committed BEFORE the run that tests
them; commit order is the timestamp.

A reverted iteration gets a full entry. A negative result
nobody recorded is a negative result somebody repeats.

```
target, transform - ffa_baseline, prior lineup
  ffc_12   -66.7 [ -92.9, -40.5]
  mfl_12   -68.8 [-114.5, -23.1]
  mfl_8    -46.5 [ -80.9, -12.0]   shuffle includes 0

depth today, identical in all three markets
              QB     RB     WR     TE     K    DEF
real        13.0   40.0   48.0   10.4   8.2   8.4
FFA         11.8   34.8   35.8   11.8   7.4   2.0
ours         8.0   52.0   35.0   17.0   8.0   8.0
                          |err vs real| 37.2
```

---

## Iteration 2 — split the bench by slot eligibility

PREDICTION COMMITTED BEFORE THE RUN.

### The change

`rostered_counts` splits the fixed 56-slot bench pool
in proportion to ASSIGNED STARTERS, which is a property
of the projection. The FLEX slot is filled by whichever
of RB/WR/TE the projection likes best, that inflates
that position's starter count, and the inflated count
then buys it a bigger share of the bench. It compounds,
and on this pool it compounds onto RB.

Split in proportion to STARTING-SLOT ELIGIBILITY
instead, which is a property of the config and cannot
compound: QB 1, RB 3, WR 3, TE 2, K 1, DEF 1.

Positions that are STREAMED still get no bench. That
half of the rule is unchanged and is not what this
iteration tests.

### Computed depth after the change, arithmetic

```
              QB    RB    WR    TE     K   DEF  |err real|
main         8.0  52.0  35.0  17.0   8.0   8.0     37.2
audible#73  16.0  48.0  32.0  16.0   8.0   8.0     33.2
THIS        14.0  43.0  35.0  20.0   8.0   8.0     27.2
real        13.0  40.0  48.0  10.4   8.2   8.4
```

Better on the two positions that matter most: QB 14
against a real 13.0 where main sits at 8.0, and RB 43
against 40.0 where main sits at 52.0. RB is the largest
single error in the table and this is the first change
to attack it directly.

WORSE ON TE, and that is predicted rather than
discovered: TE has two eligible slots against RB and
WR's three, so slot eligibility buys it more bench than
starter demand did. 17 -> 20 against a real 10.4. The
league barely benches tight ends and neither rule knows
that.

WR does not move. Both implementations sit at ~35
against a real 48.0, so the FFA comparison is silent on
the largest distance-from-real in the table. That is
iteration 3.

### Mechanism, as a claim

audible#77 established that the QB depth move is the
whole of audible#73's gain (+9.10 isolated) and that the
RB/WR/TE redistribution was NEGATIVE (-9.26). If that
holds, this iteration's gain should be roughly six
eighths of audible#73's QB move -- 8->14 against 8->16 --
minus whatever the larger RB move and the wrong-way TE
move cost.

So the claim is: a SMALLER gain than audible#73's
+18.2, in the same direction, in at least two markets.

### Predicted effect

```
  ffc_12   -66.7 -> -55   (+12)
  mfl_12   -68.8 -> -52   (+17)
  mfl_8    -46.5 -> -42   (+4)
```

Structural outcomes, which audible#73 was killed by and
which it did not predict:

```
  wasted_roster_slots  1.05 -> about 1.6   WORSE
  QB per team          1.30 -> about 2.2
  positional_surplus   5.93 -> about 6.1   WORSE
  unfillable_byes      3.00 -> about 3.1   WORSE
```

`wasted_roster_slots` counts surplus at a position that
fills at most one starting slot, so it rises whenever QB
depth rises. audible#73 took it to 1.96 at QB 16; this
should land lower because QB 14 is a smaller move, but
it should still RISE.

b4 QB control, `test_the_b4_producers_are_actually_
executed`: PREDICTED GREEN. It asserts `points_greedy`
drafts more quarterbacks than `audible_transform`.
audible#73 tied them at 3.0 and broke it; at QB 14 the
transform should land near 2.2 and stay under. THIS IS
THE RISK IN THIS ITERATION and it is named before the
run rather than after.

### Decision rule, pre-committed

KEEP only if the gap improves in at least two of three
markets AND the structural outcomes are flat or better
AND every control is green. On the prediction above the
structural outcomes get WORSE, so on my own prediction
this iteration is REVERTED. It is run anyway, because
the prediction may be wrong and because the arithmetic
says it is the closest any rule has come to what the
league actually drafts.

### Result

RAN. Depth landed exactly as the arithmetic predicted:
QB 14, RB 43, WR 35, TE 20, |err vs real| 27.2.

```
transform - ffa_baseline, prior lineup
  market  before  predicted  actual                moved
  ffc_12  -66.7    -55       -47.1 [-77.7,-16.6]   +19.6
  mfl_12  -68.8    -52       -47.9 [-84.5,-11.3]   +20.9
  mfl_8   -46.5    -42       -35.7 [-77.2, +5.8]   +10.8
```

PREDICTED VERSUS ACTUAL: the gap beat the prediction in
all three markets, by 8, 4 and 6. The direction and the
"at least two of three" claim both held. mfl_8's interval
now INCLUDES ZERO, so that market's gap is no longer
resolvably negative.

Paired on the same (season, seed) units, clustered:

```
  ffc_12  +19.58 [ -7.68,+46.84]  5/5 seasons +
  mfl_12  +20.89 [-21.15,+62.94]  3/5
  mfl_8   +10.78 [-41.32,+62.89]  3/5
  seat's own points  +14.43 / +19.02 / +3.59
  field's contribution +5.15 / +1.88 / +7.19
```

The gain is mostly the seat rather than the field, which
is the opposite of audible#73 on mfl_8. But NONE of the
three paired intervals excludes zero.

STRUCTURAL, predicted to get worse and it did:

```
  wasted_roster_slots  1.047->1.623  1.030->1.620
                       1.070->1.667
  positional_surplus   5.927->6.023  5.997->6.000
                       6.007->6.003
  unfillable_byes      3.003->3.023  3.207->3.170
                       2.977->2.973
  QB per team          1.30->2.56    1.13->2.59
                       1.16->2.65
```

b4 QB control: PREDICTED GREEN, ACTUALLY RED. The
transform ties points_greedy at 3.00 quarterbacks. The
prediction was wrong, and why it was wrong is the
session-ending finding below.

### Disposition: REVERTED

But NOT for the reason the pre-committed rule gives, and
the difference matters.

THE REASON THAT STANDS is a comparison nobody had run:
iteration 2 against iteration 1 head to head, paired on
the same units, since both share a baseline.

```
  iteration 2 minus iteration 1
  ffc_12   +1.39 [-20.62,+23.40]   1/5 seasons +
  mfl_12   -7.62 [-26.20,+10.97]   2/5
  mfl_8    +6.98 [ -9.78,+23.75]   4/5
  pooled   +0.25 [ -9.53,+10.04]
```

Iteration 2 buys +0.25 over iteration 1 and raises the
between-season variance in all three markets -- ffc's
season sd goes 9.73 to 21.96, mfl_8's 31.78 to 41.97. On
ffc it is WORSE in four of five seasons and its headline
comes from 2024 alone; leave-2024-out drops it to +10.34
against iteration 1's worst leave-one-out of +14.60. And
iteration 1 wins mfl_12 outright.

So a materially better depth table -- 27.2 against 33.2
distance from the league -- bought no measurable gain and
more variance. That is a real argument against the
premise both iterations share.

THE OTHER TWO STATED REASONS DO NOT STAND.

"Structural worse" is a true fact and an incoherent rule.
Measured on the five completed drafts with the same
formula, the real league scores 0.700 -- better than
main's 1.047 and than iteration 2's 1.623, so the metric
is not penalising the room for matching the league. But
`ffa_baseline`, the arm being chased, scores 2.097 to
2.557 on it, WORSE than either candidate, while beating
the transform by 47 to 67 points. A rule that says "keep
only if structural is flat or better" therefore forbids
by construction any change that moves the transform
toward the behaviour of the arm it is chasing. The rule
was mine and it is withdrawn.

"Control broken" does not stand at all. See below.

---

## SESSION-ENDING FINDING

The control that vetoed both iterations cannot do its
job.

`sim/test_g_b4.py::test_the_b4_producers_are_actually_
executed` asserts that `points_greedy` drafts MORE
quarterbacks than `audible_transform`, on the stated
ground that "replacement level's first-order effect in a
one-QB league is to demote QBs". It vetoed audible#73 at
QB 16 and it vetoed this iteration at QB 14.

IT FIRES ON CORRECT BEHAVIOUR. Two measurements.

THE PROSE CLAIM IS TRUE AT EVERY DEPTH. Board-level
demotion of QB1 through QB5, overall rank under vorp
minus overall rank under raw points, positive meaning
demoted:

```
  QB depth   8    +28.2 ranks
            11    +25.2
            13    +16.4      <- the league's own depth
            16    +15.6
            24     +3.4
```

The transform still demotes quarterbacks by sixteen board
ranks at the depth the league actually drafts. The level
the control asserts holds; deeper replacement erodes it
without reversing it.

THE CODED ASSERTION MEASURES SOMETHING ELSE, and it
saturates. `room.fit_room` fits roster caps from the
forty real team-seasons and gets `caps["QB"] == 3` from a
histogram of `{1: 16, 2: 23, 3: 1}` -- ONE team-season in
forty set that ceiling. `points_greedy` sits on the cap
at every depth, so the assertion is a strict `>` against
a clamped ceiling and must fail the moment the other arm
also reaches it:

```
  QB depth   points_greedy QB   transform QB   control
      8            3.00             1.50       GREEN
      9            3.00             2.00       GREEN
     10            3.00             2.50       GREEN
     11            3.00             3.00       RED
     12..16        3.00             3.00       RED
```

The threshold is ELEVEN, not fourteen, and the league's
own 13.0 sits inside the red band. Raise only that cap to
6 and the control is green at every depth tested,
including 13 and 14, because both arms are then free to
separate.

So the control and the league's ground truth are
irreconcilable as the assertion is written, and the
reason is a cap fitted from a single outlier team-season
rather than anything about replacement level.

THIS ENDS THE SESSION under the handoff's own rule: a
gate firing on correct behaviour is a finding about the
gate. It is not fixed here, deliberately -- fixing the
referee that vetoed both of this line's iterations, in
the session whose iterations it vetoed, is the exact
conflict of interest that "do not weaken a gate to make
an iteration pass" exists to prevent.

WHAT THE NEXT SESSION SHOULD FIX FIRST. The gate should
measure the claim it states -- board-order demotion of
the top quarterbacks, which is well behaved at every
depth -- or keep the draft-count form and guard against
cap saturation. Until then no depth iteration can be
evaluated, because every one of them hits this wall at
QB 11.

## Also found by the review, recorded and not fixed

  * `sim/test_g_b6.py:492` is a committed scope gate
    asserting this session writes only inside `sim/`, and
    it names `src/audible/value/replacement.py` by path.
    Both B11 and B12 authorise writing `src/audible/`, so
    that gate is stale relative to the current scope. It
    needs deliberate retirement in writing, not a silent
    edit.
  * `sim/runs/b4-transform.json` pins main's replacement
    levels, so any kept depth change requires
    regenerating it. Unbudgeted.
  * A LATENT CORRECTNESS REGRESSION in the change,
    reverted with it. Moving membership from
    `_startable_slots >= 2` to `pos not in
    NO_BENCH_DEPTH` admits a position with ZERO startable
    slots, which takes weight 0, sorts last, and becomes
    the rounding absorber -- it can go NEGATIVE. On a
    fuzzed config with TE declared but never started it
    produced `TE rostered = -1`, which makes `at_pos[-1]`
    return the WORST tight end as the replacement and
    puts twelve of them in the first twenty-four picks.
    No shipped league triggers it and `origin/main` is
    not exposed. Any future version needs a clamp.
  * `rostered_counts`'s own docstring is false on four
    counts after the change and I did not touch it -- it
    still says bench depth goes only to multi-slot
    positions, still says the split is by starter demand,
    still quotes RB35/WR52/QB8/TE17, and still cites the
    unsourced ADP composite that the test docstring
    deletes as unsourced. A wrong comment is a defect and
    this one was mine.
  * The equal-bench-share assertion I added to the test
    is nearly redundant: over ten mutations of the rule
    it never fires on anything the four `rostered` pins
    do not already catch, and it survives two mutations
    of the sort order. Its comment overstates what it
    constrains.
  * `ffa_baseline` is BIT-IDENTICAL across baseline,
    iteration 1 and iteration 2 in all 900 paired units,
    so the target is uncontaminated. That attack came
    back clean.

## Artifact naming

`b12i2-{ffc,mfl12,mfl8}.json` are iteration 2's runs.
They carry `run: b10-ffc` and so on in their own headers,
because they were produced by running the b10 configs
with `--out` pointed at a new name so the ONLY difference
from the committed baseline is the src change. That makes
them a clean paired comparison and it makes their `run:`
field wrong; audible#77 was asked to stop leaving a
reader to trip over this, so both facts are stated here.
They are kept as the evidence for a change that is NOT
shipped.
