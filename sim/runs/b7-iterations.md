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
    mean                   -34.5
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

`src/audible/value/replacement.py` only. One rule.

### Actual

*(recorded after the run)*

---

## Ranked queue after iteration 1

Re-ranked after each cycle rather than worked from a list. Current ranking by measured size:

1. **QB -68.02** — iteration 1.
2. **WR -18.48** — and the measurement points at a second defect in the same function. The
   rule lands RB 52 / WR 35; the real drafts are RB 40.0 / WR 48.0. **The rule has RB and WR
   the wrong way round**, because `assign_starters` gives every FLEX to a running back (RB 24
   starters against WR 16), and the bench is then split in proportion to that. Not touched in
   iteration 1: one change per iteration.
3. The three `audible#72` invariant findings — `seat_conflict_seen`, `sync_stale_blip`,
   `sync_stale_shrink`. Correctness, not board value; they move no arm.
4. **RB +16.18**, **K +9.47**, **TE +1.21** — all inside the noise of a 5-cluster interval.
