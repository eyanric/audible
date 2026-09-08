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

Filled in after the run.
