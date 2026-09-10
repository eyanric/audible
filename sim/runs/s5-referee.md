# S5 — fix the referee, then re-adjudicate everything it decided

`audible#87` established that the noise floor is a distribution, not a number, and that its own
variance is larger than most effects this project has measured. Every accept/reject decision in
`audible#86` and `#87` was made against a single draw of it. This session fixes the mechanism
and re-decides what the broken mechanism decided.

Scripts behind every number here, all committed (G10):
`sim/referee.py`, `sim/runs/s5_floor.py`, `sim/runs/s5_gate.py`, `sim/runs/s5_adjudicate.py`.
The floor's 24 draws are frozen in `sim/runs/s5-floor.json` so every adjudication in this
session reads the same numbers.

---

## TASK 2 — G5 rebuilt, and what it now rejects

The old gate asked one question — "did some ordering move" — through a **different code path**
than the one that decided whether the term applied. That is how `availability` passed on 214
players displaced by 8.95e-16 of floating-point residue.

Three conditions now hold together, and each exists because a specific term slipped through:

    1. the term APPLIES in at least two seasons          availability was live in one
    2. every applied cell clears MIN_SD_REL = 1e-9       that one cell was float residue
    3. the board ordering MOVES in at least two seasons  shrink was said to move none

Condition 2 is enforced inside `signals.cells`, **which `adjust` itself calls**. The gate and
the transform cannot diverge again without that one function changing under both.

### INJECTION 2 — the float-residue term FAILS, as required

`availability` unchanged from `audible#87`, through the within-position path:

    availability (scope=position): FAILS
      applies in 0/6 seasons
      cells applied/skipped: 0/24
      players displaced by season: 2019:0 2020:0 2021:0 2022:0 2024:0 2025:0
      REASON: applies in 0 season(s), needs 2
      REASON: no cell clears the minimum standard deviation
      REASON: moves an ordering in 0 season(s), needs 2

Every one of the 24 cells is skipped, including the 2022 quarterback cell that `audible#87`
applied: `sd = 8.950e-16 <= 7.974e-09`. **The published +0.071 cannot be produced any more.**

A detail the old run never surfaced: `availability` has **no value at all in 2019** — n=0 in all
four cells, because the rate is built from seasons strictly before season−1 and
`player_stats_2018` is the earliest file. It was a five-season term reported as a six-season one.

### INJECTION 3 — FAILED AS WRITTEN, and the premise is refuted

`audible#85`, `sim/signals.py`'s own docstring, and this handoff all assert that `shrink` is
**provably inert**: "uniform scaling of VORP leaves the order unchanged, and the board was
byte-identical at s=0.0 and s=0.4".

**It is not.** Measured at s=0.40, per season:

    2019  displaced   0   board identical: True
    2020  displaced 377   board identical: False
    2021  displaced   0   board identical: True
    2022  displaced   0   board identical: True
    2024  displaced 353   board identical: False
    2025  displaced   0   board identical: True

The algebra is right as far as it goes — within a position, a player and his own replacement
contract by the same factor, so VORP scales by (1−s) and no pair can cross. It assumes the
**replacement rank is stable**, and in two seasons it is not. `compute_vorp` assigns FLEX slots
by simulating every team filling its lineup from the projection-ranked pool, so compressing
each position toward its own mean changes **who wins the flex**:

    2020  RB starters 23->24   rostered 50->52   replacement rank 51->53
          WR starters 17->16   rostered 37->35   replacement rank 38->36
    2024  RB starters 23->24   rostered 50->52   replacement rank 51->53
          WR starters 17->16   rostered 37->35   replacement rank 38->36
    2021  every position unchanged  -> the board IS byte-identical

One flex slot moves from wide receiver to running back, both replacement levels move two ranks,
and the uniform-scale property breaks. Confirmed on the VORP ratios directly: in 2021 every one
of 479 players has `new/base = 0.600000` exactly, one distinct ratio; in 2020 there are **318**
distinct ratios spanning −1.03 to +3.99.

**Consequences, and they are larger than this injection:**

1. **G4 as written cannot be satisfied.** `shrink` moves an ordering in exactly two seasons,
   which meets condition 3. The rebuilt gate **passes** it. Tuning the threshold to three
   seasons purely to force the demanded verdict is the exact failure this session exists to
   fix, so it was not done. **G4: FAILS — reported, not engineered away.**
2. **`shrink` was never inert and should have been measured.** `audible#85` rejected it on a
   false premise.
3. **The replacement level is not stable under a monotone within-position rescaling.** Any
   transform that changes the *shape* of a position's distribution can silently move the
   cross-position interleave through the flex allocation, without moving a single player
   within his own position. That is a property of the transform the rebuild will inherit.

### G4/G5 — the terms this session measures

    availability (board)   PASSES  5/5 seasons  cells 5/0    min sd 5.795e-01
    snap_share             PASSES  6/6 seasons  cells 24/0   min sd 2.020e-01
    adp_gap                PASSES  6/6 seasons  cells 24/0   min sd 3.218e+00
    draft_round (rookies)  PASSES  6/6 seasons  cells 21/3   min sd 1.098e+00
    ngs_separation         PASSES  6/6 seasons  cells 12/12  min sd 3.981e-01
    ngs_rush_eff           PASSES  6/6 seasons  cells  6/18  min sd 3.411e-01
    ngs_time_to_throw      PASSES  6/6 seasons  cells  6/18  min sd 1.133e-01
    contract               PASSES  6/6 seasons  cells 24/0   min sd 1.432e-02
    noise                  PASSES  6/6 seasons  cells 24/0   min sd 5.160e-01

The skipped counts are the positional signals declining to act outside their own locus, which
is correct: `ngs_rush_eff` applies in 6 of 24 cells because it is charted for ball carriers.

### G5 — `availability` actually applies now

    scope=position  0 of 496 point values changed   (all 24 cells skipped)
    scope=board   496 of 496 changed, sd 5.795e-01, 4 distinct values

A position-level constant has zero spread *within* a position, so the within-position path
could only ever skip it or fire on rounding residue. `board` scope standardises across the pool,
which is the only route by which such a term can move the cross-position interleave — the locus
`audible#87` correctly predicted and never tested.

### INJECTION 5 — the perfect board and the shuffled board

    2019  perfect 0.000000   shuffled 53.038
    2020  perfect 0.000000   shuffled 52.123
    2021  perfect 0.000000   shuffled 42.137
    2022  perfect 0.000000   shuffled 55.229
    2024  perfect 0.000000   shuffled 53.487
    2025  perfect 0.000000   shuffled 57.802

Exact zeros, and chance is 42–58 RWRE. The metric is calibrated.

---

## TASK 4 — can the window be extended? NO, and the board is the reason

The handoff asks whether Next Gen Stats coverage back to 2016 adds seasons for
`ngs_separation`, since more seasons is the only thing that raises the LOSO's degrees of
freedom. It does not, and the binding constraint is **not** the signal:

    2016  board FAIL: espn 2016 is excluded and is not substituted
          realised FAIL: realised outcomes missing for 2016
    2017  board FAIL / realised FAIL
    2018  board FAIL / realised FAIL
    2019  board 481   realised 572   ngs_separation 125
    2023  board FAIL: espn 2023 is excluded    realised 577

ESPN is a **seven-season** vintage source beginning 2019 (`audible#83`), and realised outcomes
are pinned 2019–2025 only. Extending the NGS window would add a signal for seasons that have no
board and no truth to score it against. **Six seasons is the maximum, 2023 is permanently
missing, and the LOSO has six folds and cannot have more.** This is a hard ceiling on the
degrees of freedom available to every result in this project, and it is set by the board source.


---

## TASK 1 — the floor, drawn twenty-four times

`sim/runs/s5-floor.json` freezes all 24 draws, and `s5_floor.py` reuses the file when it
exists, so re-running the script cannot silently move a published number.

    locus   mean      sd     2.5%      97.5%     min      max
    board  +0.342   0.387   -0.516   +0.883   -0.702   +1.106
    QB     +0.218   0.192   +0.000   +0.491   +0.000   +0.491
    RB     +0.101   0.142   -0.045   +0.347   -0.105   +0.359
    WR     +0.054   0.462   -0.685   +0.678   -0.712   +0.728
    TE     +0.161   0.420   -0.507   +0.803   -0.545   +0.857

**The floor is mildly positive everywhere.** An information-free term makes the board slightly
worse on average, at every position, which is what a term carrying nothing should do. Nothing
here is negative on average, so `audible#87`'s "noise HELPS at tight end" has no support at all
once the draw is repeated.

### where the single published draw actually sat

    board  legacy +0.364   rank 11/24 among the draws
    QB     legacy +0.000   rank  1/24
    RB     legacy +0.113   rank 16/24
    WR     legacy -0.620   rank  4/24
    TE     legacy -1.083   rank  1/24

**This is the whole failure in one table.** `audible#86` and `#87` drew a salt that was
*perfectly typical board-wide* — 11th of 24 — and *extreme at three of the four positions*,
including the most extreme of 24 at both QB and TE. So the board-wide number looked
unremarkable and every positional conclusion built on it was wrong. A referee checked only
board-wide would have reported nothing amiss.

### G2 — resampling the salt widens the interval, and the old mechanism resolves nothing

The term under test here is **another information-free draw**: a thing known to carry nothing,
so an honest interval must contain zero.

    locus  conditional width  unconditional width  widened   one-draw verdict
    board            1.431              2.375       1.66x    RESOLVED BEATS FLOOR
    QB               0.000              0.972         n/a    not resolved
    RB               0.000              0.717         n/a    not resolved
    WR               1.792              2.339       1.31x    not resolved
    TE               1.559              1.857       1.19x    RESOLVED WORSE THAN FLOOR

**The broken mechanism resolves a term guaranteed to be information-free, in two of five
loci, in both directions.** The distribution says "not resolved" at all five, correctly. At QB
and RB both draws have all-zero deltas — the fit declines the noise knob outright — so the
conditional difference is identically zero with no spread and the ratio is undefined.

---

## TASK 3 — re-adjudication. Interval against interval, and NOTHING resolves.

Expected loci were stated before any number was computed (G7) and are in `PLAN` at the top of
`s5_adjudicate.py`. Every figure below is `signal - floor` with the season AND the salt
resampled together.

    signal              locus  signal delta   difference [2.5%, 97.5%]      disposition
    snap_share            RB        +0.314   +0.213 [-0.283, +0.589]   not resolved
                          WR        +0.252   +0.198 [-1.057, +1.510]   not resolved
                          TE        +0.286   +0.125 [-0.779, +1.064]   not resolved
    adp_gap               QB        +0.216   -0.002 [-0.827, +0.497]   not resolved
                          RB        -0.112   -0.213 [-0.763, +0.169]   not resolved
                          WR        -0.181   -0.235 [-1.506, +1.208]   not resolved
                          TE        -0.253   -0.414 [-1.431, +0.547]   not resolved
    draft_round           RB        +0.109   +0.008 [-0.508, +0.333]   not resolved
    (rookies only)        WR        +0.032   -0.023 [-1.296, +1.377]   not resolved
                          TE        +0.147   -0.013 [-0.977, +0.966]   not resolved
    ngs_separation        WR        -0.874   -0.928 [-2.328, +0.481]   not resolved
    ngs_rush_eff          RB        +0.087   -0.014 [-0.490, +0.269]   not resolved
    ngs_time_to_throw     QB        +0.669   +0.451 [-0.194, +1.595]   not resolved
    contract              QB        +0.000   -0.218 [-0.972, +0.000]   not resolved
                          RB        +0.177   +0.076 [-0.475, +0.479]   not resolved
                          WR        +0.469   +0.414 [-0.651, +1.585]   not resolved
                          TE        +0.787   +0.626 [-0.302, +1.633]   not resolved
    availability       board        +0.813   +0.445 [-0.802, +1.988]   not resolved

**Eighteen loci across eight terms. Not one resolves.** Positive is worse, so most of these
terms make the board slightly worse than an information-free term does, and none of it is
distinguishable from zero.

### old decision beside new (G6)

    snap share        REVERTED        -> NOT RESOLVED
    adp gap           REVERTED        -> NOT RESOLVED
    rookie capital    REVERTED        -> NOT RESOLVED
    ngs_rush_eff      REVERTED        -> NOT RESOLVED
    ngs_time_to_throw REVERTED        -> NOT RESOLVED
    contract          REVERTED        -> NOT RESOLVED
    ngs_separation    UNRESOLVED      -> NOT RESOLVED (carriers now identified)
    availability      NEVER MEASURED  -> NOT RESOLVED (first real measurement)

**Zero of seven flip from reject to accept.** But all seven change what is being claimed, and
the change is not cosmetic: REVERTED asserts a term was tested and failed, and NOT RESOLVED
asserts the harness cannot tell. Six seasons never had the power to support the first claim.

### INJECTION 1 — what the single draw would have decided

Five loci get a **different disposition** from the one-draw mechanism, and every one of the five
is a **false resolution** the distribution refuses:

    snap_share@RB          one draw: RESOLVED WORSE   distribution: not resolved
    draft_round@WR         one draw: RESOLVED WORSE   distribution: not resolved
    ngs_time_to_throw@QB   one draw: RESOLVED WORSE   distribution: not resolved
    contract@WR            one draw: RESOLVED WORSE   distribution: not resolved
    contract@TE            one draw: RESOLVED WORSE   distribution: not resolved

Interval widths grow by **1.06x to 2.90x** once the salt is resampled. The damage the old
mechanism did is therefore measurable: on this set it manufactures resolution in 5 of 18 loci,
**28%**, all in the same direction.

### INJECTION 4 — the dilution, per signal

    ngs_separation     WR  -0.874 at locus vs +0.287 board-wide   sign FLIPS
    ngs_time_to_throw  QB  +0.669 at locus vs +0.579 board-wide
    ngs_rush_eff       RB  +0.087 at locus vs +0.027 board-wide
    contract           QB  +0.000 at locus vs +0.489 board-wide
    snap_share         RB  +0.314 at locus vs -0.539 board-wide   sign FLIPS
    adp_gap            QB  +0.216 at locus vs -0.457 board-wide   sign FLIPS

**Three times the board-wide figure carries the opposite sign to the locus figure.** Separation reads
as a harm board-wide (+0.287) and a benefit at wide receiver (−0.874); snap share reads as a
benefit board-wide (−0.539) and a harm at running back (+0.314). Averaging a positional effect
across four positions does not merely weaken it — it can invert it.

### `availability` — the first real measurement, and a refuted prediction

    board  +0.813 [+0.139, +1.957]   floor +0.368   difference +0.445, not resolved
    fitted lambda 2020:0.0  2021:-0.1  2022:+0.05  2024:+0.1  2025:-0.1   SIGN FLIPS

Five seasons, not six: the rate is built from seasons strictly before season−1 and
`player_stats_2018` is the earliest file, so **2019 has no value at all** and the term was a
five-season term reported as six.

**The structural prediction is REFUTED, and the reason matters.** `audible#87` predicted, and
this session restated, that a value constant within a position cannot reorder that position, so
every per-position figure must be exactly +0.000. Measured: RB +0.159, QB −0.036, WR −0.028,
TE +0.0004.

The premise is exactly right and the conclusion does not follow:

    2020  QB order_same=True  pool  9->11     2024  QB order_same=True  pool 10->12
          RB order_same=True  pool 54->58           RB order_same=True  pool 52->43
          WR order_same=True  pool 44->37           WR order_same=True  pool 47->53
          TE order_same=True  pool 21->22           TE order_same=True  pool 19->20
    2021  every position order_same=True, pool unchanged -> per-position exactly +0.0000

**The within-position order never changes — not once, in any position, in any season.** What
changes is POOL MEMBERSHIP. Per-position RWRE is scored over the members a position contributes
to the top-128 pool, and the interleave decides that membership. So a term that moves only the
interleave changes every position's score without a single within-position swap. In the three
seasons where pool composition happens not to move, the per-position figures are exactly
+0.0000, which is why the prediction looked confirmed.

This is the same shape as the `shrink` finding: **the per-position metric is not independent of
the cross-position ordering**, and a "locus" is therefore not as clean a separation as three
sessions have assumed.

---

## TASK 4 — `ngs_separation` settled: it rests on two seasons

    WR   signal -0.874 [-1.957, +0.124]   floor +0.054 [-1.090, +1.113]
         difference -0.928 [-2.328, +0.481]   NOT RESOLVED
         fitted lambda +0.05 in all six folds -- no sign flip, the one term that is stable

    per season  2019:-0.82  2020:+0.20  2021:-2.79  2022:-0.26  2024:+0.73  2025:-2.30

**2021 and 2025 carry 83% of it.** Sum of the negative seasons is −6.17, of which −5.09 is
those two.

    dropping 2021        signal -0.491   difference -0.612 [-2.060, +0.806]  not resolved
    dropping 2025        signal -0.588   difference -0.665 [-2.124, +0.755]  not resolved
    dropping both        signal -0.038   difference -0.204 [-1.429, +1.187]  not resolved

Without those two seasons the effect is **−0.038 — nothing at all.**

**DISPOSITION: NOT RESOLVED, and it is the best-behaved term measured.** It has the largest
point estimate of any signal, the only fitted weight that is stable across all six folds, and
it is WR-specific as its mechanism requires. It also rests on two seasons out of six and cannot
be separated from an information-free term. Both halves are true and neither cancels the other.

**The window cannot be extended** — see Task 4 above. The board, not Next Gen Stats, is the
binding constraint.

---

## G9 — POWER. Resolution is NOT possible at six seasons, and this is the session's result.

Stated as plainly as a win, because it is the finding:

**No signal tested can resolve against an honestly-measured floor with six seasons, and none
did — eighteen loci, zero resolutions.**

The arithmetic is not close. Folding the salt's variance in widens intervals by 1.06x to 2.90x,
and the half-width of the difference interval is what an effect has to exceed to exclude zero:

    locus   typical difference half-width   what an effect must exceed
    RB                     0.36 - 0.48                  ~0.4
    QB                     0.49 - 0.90                  ~0.7
    TE                     0.92 - 0.99                  ~1.0
    WR                     1.20 - 1.40                  ~1.4

`ngs_separation` at WR is the largest effect this project has ever measured at **−0.874**,
against a bar of roughly **1.4**. It is not marginal; it is short by a factor of about 1.6, and
that is with two of six seasons carrying 83% of it.

**Three constraints multiply, and only one is fixable:**

1. **Six seasons is a hard ceiling.** ESPN begins in 2019, outcomes are pinned 2019–2025, and
   2023 does not exist. The LOSO has six folds and cannot have more.
2. **The floor's own sd is 0.14 to 0.46**, comparable to every effect measured.
3. **The season is the resampling unit**, and six clusters is very few.

What this rules out: **any future session that tests one signal at a time on this harness and
expects a resolution.** That design is exhausted. `audible#84`, `#85`, `#86`, `#87` and this
session have now run it eleven times between them and produced zero honest resolutions.

What it does not rule out: a transform that changes the ordering *shape* rather than nudging it
with a scalar weight — which is what the standing goal actually asks for — or an outcome metric
with more than six degrees of freedom.
