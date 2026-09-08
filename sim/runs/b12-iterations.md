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

Filled in after the run.
