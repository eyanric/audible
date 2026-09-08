# B7 — the iteration log

One entry per cycle, fixed schema, committed **before** the run it predicts. The commit order
is the evidence that the prediction preceded the measurement; a prediction written after the
number is not a prediction, and this file is the only thing that makes the difference
checkable by someone who was not here.

Every entry records the same fields whether the iteration succeeded or failed. An iteration
that predicted wrongly is the most informative kind and is kept in full.

---

## Baseline — `audible#71`, artifact `sim/runs/b5-vintage.json`

Measured, not quoted from the handoff (which agreed):

```
transform_minus_ffa_baseline   -66.7 [ -92.9,  -40.5]
transform_minus_points        +122.3 [ -66.5, +311.2]
transform_minus_adp            -35.4 [ -94.2,  +23.4]
ffa_baseline_minus_points     +189.1 [  +2.9, +375.3]
ffa_baseline_minus_adp         +31.3 [ -29.7,  +92.4]
ceiling_minus_adp             +300.4 [+140.0, +460.8]
real_minus_shuffle             +97.3 [ +58.4, +136.3]
shuffle_minus_bot              +58.7 [ +12.5, +104.9]

by position (transform - ffa_baseline):
  QB -68.02   WR -18.48   RB +16.18   TE +1.21   K +9.47   DEF 0.00
```

`n=300` pairs, 5 season clusters, 4 df, t = 2.776 throughout.

### Ground truth measured for this session

How many of each position is ACTUALLY rostered inside 128 picks, from the five completed
league-6012 drafts (`espn_draft_6012_<season>.json`, parsed through `sim.room.load_real_draft`
so positions normalise exactly as everywhere else in the harness):

```
        QB    RB    WR    TE     K   DEF
2021    13    38    48    12     8     9
2022    12    42    48    10     8     8
2023    14    40    48    10     8     8
2024    12    41    48    10     9     8
2025    14    39    48    10     8     9
MEAN  13.0  40.0  48.0  10.4   8.2   8.4
```

And the same for the FFC ADP boards' top 128, which is what `rostered_counts`' docstring
validates against:

```
        QB    RB    WR    TE     K   DEF   first DEF   first K
2021    15    47    49    13     0     4         103        143
2022    16    50    48    12     0     2         113        141
2023    17    47    50    13     0     1         125        139
2024    18    45    53    12     0     0         133        138
2025    17    39    58    10     0     4          56        140
MEAN  16.6  45.6  51.6  12.0   0.0   2.2
```

**Three refutations of the docstring in `rostered_counts`, all measured:**

1. *"ADP's first 128 picks hold 43 RB / 53 WR / 16 QB / 16 TE"* — matches **no season**. No
   season has RB 43; only 2024 has WR 53, and its RB is 45, QB 18, TE 12. The figure is a
   composite or comes from a board not pinned here.
2. *"and zero D/ST or K (first D/ST at 132, first K at 131)"* — the ADP boards do hold zero K,
   but D/ST appears inside 128 in four of five seasons (as high as rank 56 in 2025). First K is
   138-143, never 131; first D/ST is 56-133, never 132.
3. **The deeper error is the choice of ground truth.** The docstring calls ADP *"the only
   ground truth available for how many of each position actually gets drafted"*. It is not:
   five completed drafts of this exact league are pinned in the same cache. And ADP is
   demonstrably the wrong proxy — it holds **zero kickers** in the top 128 while the real
   drafts take **8.2 of them**, one per team, every year.

---

## Iteration 1 — the QB replacement baseline

**PREDICTION COMMITTED BEFORE THE CHANGE. Nothing below the "actual" heading existed when this
was written.**

### Gap before

`transform - ffa_baseline` = **-66.7 [-92.9, -40.5]**, of which **QB is -68.02** — the whole
of it, with RB (+16.18) and K (+9.47) partly offsetting WR (-18.48).

### Mechanism, stated as a claim

`rostered_counts` allocates bench depth only to positions where
`_startable_slots(config, pos) >= 2`. In a 1-QB league QB is eligible in exactly one starting
slot — the FLEX takes RB/WR/TE — so `_startable_slots(QB) == 1` and **QB is excluded from the
bench split entirely**, receiving starters only: eight in an eight-team league.

The rule's own docstring says why it excludes single-slot positions: *"A team that can start
exactly one D/ST gains nothing from a second one, so it drafts one and streams the rest."*
That is true of D/ST and K and false of QB. Slot count cannot distinguish *"one slot because
the position is a streamed specialist"* from *"one slot because this league is 1-QB"*, and the
proxy therefore misclassifies exactly one position.

The separation is measurable and is in the table above. Across five real drafts, per team:

```
  K    8.2 / 8 = 1.02 rostered per team   never a second
  DEF  8.4 / 8 = 1.05 rostered per team   never a second
  QB  13.0 / 8 = 1.63 rostered per team   most teams carry a backup
```

A backup quarterback is injury insurance for a position whose starter plays every snap and
whose replacement is not free. That is what the rule meant to capture and what slot count
fails to.

### Predicted effect

Replacing the slot-count proxy with the property it stands for puts QB into the bench split.
Computed from the split arithmetic, before any run:

```
  QB baseline rank   8 -> 16   (all five seasons)
  RB                52 -> 48
  WR                35 -> 32
  TE                17 -> 16

  QB baseline points, and the drop:
    2021  325.0 -> 276.0   -49.1
    2022  316.0 -> 270.5   -45.5
    2023  290.3 -> 267.0   -23.3
    2024  296.0 -> 269.8   -26.3
    2025  302.2 -> 274.2   -28.1
    mean                   -34.44
```

A lower baseline raises every quarterback's VORP, so quarterbacks move up the board and get
drafted earlier. The QB decomposition term is -68.02 because audible's starting quarterback is
worse than `ffa_baseline`'s; closing the baseline gap should close most of that term.

**Predicted: the QB term moves from -68.02 to between -34 and +10** — at least half the gap,
and possibly through zero. **Predicted: `transform - ffa_baseline` improves from -66.7 to
between -35 and +5.**

**AND A PREDICTED OVERSHOOT, recorded so it cannot be claimed as a success afterwards.** QB16
is not the measured depth. Two independent sources put the right answer near 12-13:

```
  real 6012 drafts   QB 13.0  (range 12-14)
  FFA's own baseline QB 11-13 (2021-2025: 12, 13, 12, 11, 11)
```

The proportional split lands on 16 because it gives every bench position the same
bench-per-starter ratio, and quarterbacks are not benched at the same rate as backs. So this
iteration is expected to **overshoot in the other direction** — a baseline slightly too deep
rather than far too shallow. If the QB term lands positive and large (say beyond +15), that is
the overshoot and it is iteration 2's work, not a failure of this mechanism.

**Falsification: if the QB term closes by less than half (stays below -34), the mechanism is
wrong and the loop stops.**

### Change

`src/audible/value/replacement.py`, one rule. The bench-eligibility test

```python
depth = sorted((pos for pos in counts if _startable_slots(config, pos) >= 2), ...)
```

becomes

```python
depth = sorted((pos for pos in counts if pos not in NO_BENCH_DEPTH), ...)
```

with `NO_BENCH_DEPTH = frozenset({"K", "DEF", "DST", "D/ST", "DL", "LB", "DB"})`.
`_startable_slots` is untouched and still used elsewhere; `audible/draft/ordering.py` keeps its
own hand-maintained mirror of it, which is therefore still in step.

**THE IDP ENTRIES CHANGE NOTHING TODAY, and two drafts of this note got that wrong before a
reviewer measured it.** `sleeper_boyfun` sets `replacement_bench_slots = 0`, so `rostered_counts`
returns at its `bench <= 0` guard before the eligibility set is ever read -- that league's board
is sha-identical under the old rule, under `{K, DEF}` alone, and under what shipped. The entries
are a guard for the day that config turns a bench on, not a fix for anything now. The measured
blast radius is:

```
  espn_danger_zone   adds QB   removes nothing
  espn_davis_drive   adds QB   removes nothing
  espn_green_hope    adds QB   removes nothing
  sleeper_boyfun     adds nothing, removes nothing -- byte-identical board
```

`tests/test_replacement_baseline.py::test_replacement_lands_where_the_market_drafts` also
changed, and that needs saying plainly rather than being buried in a diff: **it pinned the
defect.** It named RB, WR and TE and never named QB -- but it also asserted
`drafted == teams * rounds`, and with the other five pinned that conservation forces QB to
exactly 8. It did not omit the quarterback, it pinned him at the wrong value without saying so,
which is why fixing the rule made it fail on three counts that never mention QB. It now asserts
every position including QB, and its anchor is the completed drafts rather than the unsourced
ADP composite.

### Actual

Run `sim/runs/b7-iter1.json` against baseline `sim/runs/b5-vintage.json`. Byte-identical
configs but for the run name, so the only difference is the `src/` change.

```
                                    before                 after      delta
transform_minus_ffa_baseline  -66.7[-92.9,-40.5]   -48.5[-71.0,-26.1]   +18.2
transform_minus_points       +122.3[-66.5,+311.2] +140.5[-44.1,+325.2]  +18.2
transform_minus_adp           -35.4[-94.2,+23.4]   -17.2[-74.0,+39.6]   +18.2
ffa_baseline_minus_points    +189.1[ +2.9,+375.3] +189.1[ +2.9,+375.3]   +0.0
ceiling_minus_adp            +300.4[+140.0,+460.8] +331.9[+158.3,+505.6] +31.5
real_minus_shuffle            +97.3[+58.4,+136.3]  +97.3[+58.4,+136.3]   +0.0
shuffle_minus_bot             +58.7[+12.5,+104.9]  +58.7[+12.5,+104.9]   +0.0

by position (transform - ffa_baseline):
  before   QB -68.02  WR -18.48  RB +16.18  TE  +1.21  K  +9.47  DEF 0.0
  after    QB -10.93  WR -41.59  RB +16.95  TE  -8.79  K  -0.80  DEF 0.0
  delta    QB +57.09  WR -23.11  RB  +0.77  TE -10.00  K -10.27
```

### Predicted versus actual

**QB: AGREE.** Predicted the term would move from -68.02 to between -34 and +10; it landed at
**-10.93**. Predicted the baseline would go rank 8 -> rank 16 in all five seasons with a mean
points drop of 34.44; both are what the change produced, verified before the run. (The
prediction said 34.5, which was the mean of the already-rounded per-season figures.) The
mechanism is confirmed at the predicted position.

**AGGREGATE: MISS, and the miss is the informative part.** Predicted `transform - ffa_baseline`
would land between -35 and +5. It landed at **-48.5** -- an improvement of +18.2, but well
short of the range.

**Diagnosis. The bench pool is conserved and I did not model the redistribution.** There are
`8 x 7 = 56` bench slots and the split spends all of them. Giving QB its share took slots from
everyone else:

```
              QB    RB    WR    TE
  before       8    52    35    17
  after       16    48    32    16
```

QB gained 8; WR lost 3, RB lost 4, TE lost 1. A **shallower** WR baseline means the baseline
player is BETTER, so every receiver's VORP falls and receivers get drafted later -- and the
real market takes **48** receivers, so WR needed to go deeper, not shallower. WR therefore
moved the wrong way and gave back 23.1 of the 57.1 that QB won. TE and K gave back another
20.3 between them.

The QB prediction was right. The aggregate prediction was wrong because it treated one
position's baseline as independent of the others when the pool that funds them is fixed.

**The predicted overshoot did not happen.** QB16 is deeper than both the real market's 13.0 and
FFA's 11-13, so I predicted the QB term might overshoot past +15. It did not -- it stopped at
-10.93, still slightly short of parity. Recorded because predicting a thing that then fails to
occur is as much a correction as predicting one that does.

### Controls

```
shuffle - bot     +58.7 [+12.5, +104.9]   unchanged to the decimal
real - shuffle    +97.3 [+58.4, +136.3]   unchanged to the decimal
bot advantage      -4.09                  unchanged; at chance
adp advantage    +134.06                  unchanged; required arm present
invariants        440 checks, 3 violations -- the same three audible#72 reported.
                  No new invariant fired.
default suite     556 passed, 1 xfailed
```

**WHICH ARMS MOVED IS ITSELF A CHECK, and it passed exactly.** Only three arms moved:
`audible_transform` (+98.69 -> +116.88), `hindsight_board` (+434.46 -> +465.98) and
`hindsight_total` (+400.61 -> +394.99). Every one of those orders on `vorp_rank` and therefore
consumes replacement levels. Every arm that does not -- `points_greedy` and `hindsight_points`
(raw points), `adp` and `adp_board` (market order), `ffa_baseline` and `ffa_vor` (FFA's own
depths), `scarcity_only`, `shuffle`, `bot` -- is unchanged to the decimal. A change to
replacement level that had moved the ADP arm would have meant something was wrong.

**`real` DID NOT MOVE, AND THAT IS A LIMIT ON THIS WHOLE ITERATION.** The `real` arm is the
cockpit's own `the_call` path and it is unchanged at +151.91, because `sim/seat.board_from_season`
deliberately does not call `compute_vorp` -- its value is linear in ADP rank, documented at
`sim/seat.py:110-123` as a refusal to invent projections. So the harness measures this fix on
`audible_transform` and cannot say what it does to the arm that models the live cockpit. The
fix reaches production through `build_board_from_lines`, which production does use; the sim's
`real` arm is simply not wired to it.

**The ceiling moved too, by +31.5.** `hindsight_board` is built through the same value engine,
so the ceiling this run is read against is not the ceiling the baseline was read against.
Fraction-of-ceiling is therefore quoted against each run's own ceiling and not across the two.

### Walk-forward

```
                    before                 after            delta
  in  (2021-2023)  -79.8 [ -95.0,  -64.7]  -52.6 [ -98.2,   -7.0]  +27.2
  out (2024-2025)  -52.8 [-357.4, +251.8]  -39.5 [-384.7, +305.7]  +13.3
```

Both splits improved and the sign is the same in both. The improvement is smaller
out-of-sample (+13.3 against +27.2), which is the shape overfitting would take -- but the
out-of-sample split has **two season clusters, one degree of freedom and a t quantile of
12.706**, so its interval spans 690 points and resolves nothing at all. It is on the page
because a reader must be able to see that it resolves nothing, not because it says the fix
generalises.

### The mechanism does not survive its own follow-up measurement

Two checks were run after the result came in, both prompted by an adversarial review, and
between them they refute the stated mechanism.

**1. The isolated QB move does not produce the gain.** Three rules over identical seeds, so
the only difference between them is the rule:

```
  old       bench to positions with >= 2 startable slots      (what shipped before)
  oldqb16   QB pinned to 16, RB/WR/TE HELD at 52/35/17        (QB move alone)
  ship      QB in the split, pool conserved, RB/WR/TE 48/32/16
```

```
  ship - old        +18.99 [ -7.68, +45.66]
  oldqb16 - old      -6.18 [-47.11, +34.76]    <- the QB move ALONE
  ship - oldqb16    +25.17 [-10.06, +60.40]    <- the redistribution
```

The QB baseline move on its own is **negative**. What moved the number is the redistribution
out of RB/WR/TE that the conserved pool forces -- the thing this log called a "give-back" two
sections above. (An independent reviewer running a differently-constructed counterfactual, one
that conserves the pool rather than over-rostering, split it +9.10 / +9.09 instead. The two
constructions disagree on the split and agree on what matters: **the QB move alone is not
+18.2.**)

**2. The market anchor is not the optimum, and is the worst point tested.** QB depth pinned at
each value, everything else as shipped, 12 seeds x 5 seasons:

```
  QB 11   -63.24 [-127.30,   +0.82]
  QB 13   -80.12 [-105.04,  -55.19]   <- the MEASURED market depth. Worst of the five.
  QB 16   -62.78 [-102.56,  -23.01]   <- what shipped
  QB 18   -50.86 [ -97.75,   -3.96]   <- best of the five
  QB 22   -62.90 [-109.77,  -16.04]
```

The mechanism this iteration stated was *"set the baseline where the market actually rosters"*.
The market rosters 13.0. **QB13 is the worst of the five points tested.** Whatever produced the
improvement, it is not agreement with the market.

And the intervals span 40 to 64 points and overlap almost entirely, so the sweep cannot
identify an optimum either. That is the second finding: **this instrument cannot resolve QB
depth at all.** Five season-clusters at four degrees of freedom is not enough to choose between
11 and 22.

### Verdict: MECHANISM REFUTED. The loop stops here.

Two of the registered stopping rules fire:

> *"Stop when a fix fails to close its predicted gap. The mechanism was wrong; more iterations
> would be guessing."*

The gap closed -- `transform - ffa_baseline` really did go -66.7 to -48.5, reproducibly, and
every control held. But G2 asks whether it closed **for the predicted reason**, and it did not.
The prediction named the QB baseline; the QB baseline alone is worth -6.2 to +9.1 depending on
how the counterfactual is built, not +18.2.

> *"Stop when the largest remaining gap is inside its own interval -- at that point the
> instrument cannot resolve the next fix and more iterations are noise."*

The QB sweep's five points sit inside one another's intervals. Iterating on WR next would be
choosing between numbers this harness cannot distinguish.

**The change is KEPT, and the causal claim is WITHDRAWN.** Those are separable, and both halves
matter:

- The defect is real and independently established. `rostered_counts` gave a 1-QB league's
  quarterback starters-only depth because `_startable_slots(QB) == 1` grouped it with D/ST and
  K. The market rosters 13.0 QBs, not 8. The docstring validating the rule cited an ADP
  composite that matches no pinned season, and validated against ADP at all -- a list holding
  zero kickers where the real drafts take 8.2. The guard that should have caught it pinned the
  defective value. None of that depends on the arm numbers.
- The claim that fixing it is worth +18.2 **is withdrawn**. The measurement does not support
  attributing the move to the QB baseline, and the follow-up sweep says the stated mechanism --
  match the market -- points at the worst of the five depths tried.

What this session actually produced is one correctness fix whose board effect is **not
explained**, plus a measured demonstration that the harness cannot resolve the parameter it
changed. That is a smaller result than the loop was designed to produce and it is the result.

### What would make the next attempt resolvable

The binding constraint is five season-clusters. `sim/runs/b7-iterations.md` cannot choose
between QB11 and QB22 because every interval is ±40 or worse at 4 df. The AFTERWARDS list in
the B7 handoff already names the fix: pin historical FFC boards and completed 6012 drafts for
2018-2020 and the harness goes to eight clusters. Nothing in the queue below is worth
attempting before that.

## Ranked queue after iteration 1

Re-ranked after each cycle rather than worked from a list. Current ranking by measured size:

1. ~~**QB -68.02**~~ — iteration 1, closed to **-10.93**.
2. **WR -41.59** — now the largest, and iteration 1 made it worse by taking bench slots from
   it. The rule lands WR 32 on the FFA board where the real drafts take **48**. The cause is
   upstream of `rostered_counts`: `assign_starters` gives every FLEX to a running back (RB 24
   starters against WR 16 on that board), and the bench is then split in proportion to starter
   count, so the flex allocation decides the bench allocation twice over. Note the same fixture
   question cuts the other way in `tests/fixtures/espn_board_projections.json`, where the flex
   goes to WR and the rule lands WR 48 / RB 32 -- so this is a property of the projection
   curve, not a constant, and any fix has to hold for both.
3. The three `audible#72` invariant findings — `seat_conflict_seen`, `sync_stale_blip`,
   `sync_stale_shrink`. Correctness, not board value; they move no arm and no interval.
4. **TE -8.79**, **RB +16.95**, **K -0.80** — inside the noise of a 5-cluster interval.
