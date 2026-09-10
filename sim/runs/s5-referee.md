# S5 — fix the referee, then re-adjudicate everything it decided

`audible#87` established that the noise floor is a distribution, not a number, and that its own
variance is larger than most effects this project has measured. Every accept/reject decision in
`audible#86` and `#87` was made against a single draw of it. This session fixes the mechanism
and re-decides what the broken mechanism decided.

Scripts behind every number here, all committed (G10): `sim/referee.py`, and under `sim/runs/`
`s5_floor.py`, `s5_gate.py`, `s5_adjudicate.py`, `s5_probe.py`. Their raw output is committed
beside them as `s5-*.out`, and the floor's 40 draws are frozen in `s5-floor.json` so every
adjudication reads the same numbers.

**The adversarial review (G15) changed this document's headline. See the last section.**

---

## TASK 2 — G5 rebuilt

The old gate asked one question — "did some ordering move" — through a **different code path**
than the one that decided whether the term applied. That is how `availability` passed on 214
players displaced by 8.95e-16 of floating-point residue.

Four conditions now hold together, and each exists because a specific term slipped through:

    1. the term APPLIES in at least two seasons               availability was live in one
    2. every applied cell clears MIN_SD_REL = 1e-9            that one cell was float residue
    3. the board ordering MOVES in at least two seasons       the weakest of the four
    4. a POSITION-SCOPE term moves a WITHIN-POSITION ordering shrink moves none

Condition 2 is enforced inside `signals.cells`, **which `adjust` itself calls**. The gate and
the transform cannot diverge again without that one function changing under both. Verified: the
set of cells `cells` marks APPLIED equals the set `adjust` modifies, 0 divergences over 159
term-season-lambda checks.

### INJECTION 2 — the float-residue term FAILS, as required

`availability` unchanged from `audible#87`, through the within-position path:

    availability (scope=position): FAILS
      applies in 0/6 seasons          cells applied/skipped: 0/24
      players displaced: every season 0
      REASON: applies in 0 season(s), needs 2
      REASON: no cell clears the minimum standard deviation
      REASON: moves an ordering in 0 season(s), needs 2

Every one of the 24 cells is skipped, including the 2022 quarterback cell that `audible#87`
applied: `sd = 8.950e-16 <= 7.974e-09`. **The published +0.071 cannot be produced any more.**

A detail the old run never surfaced: `availability` has **no value at all in 2019** — n=0 in all
four cells, because the rate is built from seasons strictly before season−1 and
`player_stats_2018` is the earliest file. It was a five-season term reported as a six-season one.

### INJECTION 3 — `shrink` is NOT INERT. The premise three handoffs carried is refuted.

`audible#85`, `sim/signals.py`'s own docstring, and this handoff all assert that `shrink` is
**provably inert**: "uniform scaling of VORP leaves the order unchanged, and the board was
byte-identical at s=0.0 and s=0.4".

**It is not.** At s=0.40:

    2019 displaced   0 (identical)   2020 displaced 377   2021 displaced   0 (identical)
    2022 displaced   0 (identical)   2024 displaced 353   2025 displaced   0 (identical)

The algebra is right as far as it goes — within a position, a player and his own replacement
contract by the same factor, so VORP scales by (1−s) and no pair can cross. It assumes the
**replacement rank is stable**, and in two seasons it is not. `compute_vorp` assigns FLEX slots
by simulating every team filling its lineup from the projection-ranked pool, so compressing each
position toward its own mean changes **who wins the flex**:

    2020 and 2024   RB starters 23->24  rostered 50->52  replacement rank 51->53
                    WR starters 17->16  rostered 37->35  replacement rank 38->36
    2021            every position unchanged  ->  the board IS byte-identical

In 2021 all 479 players share the VORP ratio `0.600000` exactly — one distinct ratio. In 2020
there are **318** distinct ratios spanning −1.03 to +3.99.

**And it is a knife edge, not a magnitude effect:**

    2020  first flip at s = 0.011      2024  first flip at s = 0.059
    2019, 2021, 2022, 2025  no flip anywhere in (0, 0.400]

**A 1.1% contraction flips a flex slot.** So "the replacement level is not stable under a
monotone within-position rescaling" is understated: it is not stable under a 1% one. Any
transform that changes the *shape* of a position's distribution can move the cross-position
interleave without moving a single player within his own position. The rebuild inherits this.

### G4 — the gate DOES reject `shrink`, on a condition that names the mechanism

`shrink` moves an ordering in exactly two seasons, so condition 3 does not reject it. Raising
that count to three purely to force the demanded verdict would be gerrymandering. Condition 4
is not: **a term that claims to separate players inside a position must be shown to do that**,
and `shrink` provably cannot, because it multiplies each position by one positive scalar.

    term                scope      seasons moving a WITHIN-POSITION ordering
    shrink (s=0.40)     position                                        0/6   <== REJECTED
    snap_share          position                                        6/6
    adp_gap             position                                        6/6
    draft_round         position                                        6/6
    ngs_separation      position                                        6/6
    ngs_rush_eff        position                                        6/6
    ngs_time_to_throw   position                                        6/6
    contract            position                                        6/6
    noise               position                                        6/6
    availability        board                             exempt by scope

Every real position-scope term passes 6/6 and `shrink` fails 0/6. A `board`-scope term is
exempt by construction, because moving only the interleave is exactly what it claims to do.

`shrink` is also now run **through the gate itself** rather than counted by hand —
`ordering_gate` takes an `order_fn` for terms that have no cells at all. `audible#87`'s
injection counted displacements in a script, which is not the same as running the gate.

    shrink (scope=position): FAILS
      REASON: position-scope term moves a WITHIN-POSITION ordering in 0 season(s), needs 2
              -- it carries no within-position information

**G4: SATISFIED.**

### G5 — `availability` actually applies now

    scope=position    0 of 496 point values changed   (all 24 cells skipped)
    scope=board     496 of 496 changed, sd 5.795e-01, 4 distinct values

    availability (board)   PASSES  5/5 seasons  cells 5/0    min sd 5.795e-01
    snap_share             PASSES  6/6 seasons  cells 24/0   min sd 2.020e-01
    adp_gap                PASSES  6/6 seasons  cells 24/0   min sd 3.218e+00
    draft_round (rookies)  PASSES  6/6 seasons  cells 21/3   min sd 1.098e+00
    ngs_separation         PASSES  6/6 seasons  cells 12/12  min sd 3.981e-01
    ngs_rush_eff           PASSES  6/6 seasons  cells  6/18  min sd 3.411e-01
    ngs_time_to_throw      PASSES  6/6 seasons  cells  6/18  min sd 1.133e-01
    contract               PASSES  6/6 seasons  cells 24/0   min sd 1.432e-02
    noise                  PASSES  6/6 seasons  cells 24/0   min sd 5.160e-01

A position-level constant has zero spread *within* a position, so the within-position path could
only ever skip it or fire on rounding residue. `board` scope standardises across the pool, which
is the only route by which such a term can move the interleave.

**`MIN_SD_REL` is not doing the work, and should be retired.** Its tightest real cell is
`contract` 2025 RB at sd 1.43e-02 against a threshold of 1e-9 — seven orders of magnitude of
headroom. Of 217 cells examined, 20 were skipped by the threshold, and **all 20 held exactly one
distinct value**. `distinct <= 1` reproduces every skip with no tunable constant at all, which is
strictly better for a session whose thesis is "do not tune the referee". Left as-is this session
because changing it now would move numbers after the review; it is the first thing to change next.

### INJECTION 5 — the perfect board and the shuffled board

    2019 perfect 0.000000 shuffled 53.038    2020 perfect 0.000000 shuffled 52.123
    2021 perfect 0.000000 shuffled 42.137    2022 perfect 0.000000 shuffled 55.229
    2024 perfect 0.000000 shuffled 53.487    2025 perfect 0.000000 shuffled 57.802

Exact zeros, chance is 42–58. The metric is calibrated.

---

## TASK 1 — the floor, drawn forty times

**Forty, not twenty-four, and the count is forced.** A two-sided reference-set test against K
draws cannot report a p below `2/(K+1)`. K=24 bottoms out at **0.080** and therefore **cannot
express a 5% test at any effect size**. K=39 is the smallest that reaches 0.050. This session
first drew 24, and the adversarial review showed that number could not do the job.

    locus   mean      sd     2.5%      97.5%     min      max
    board  +0.326   0.378   -0.454   +0.914   -0.702   +1.106
    QB     +0.219   0.191   +0.000   +0.492   +0.000   +0.526
    RB     +0.104   0.136   -0.107   +0.338   -0.169   +0.359
    WR     +0.050   0.497   -0.715   +0.774   -0.830   +1.380
    TE     +0.196   0.424   -0.548   +0.764   -0.683   +0.857

**The floor is mildly positive everywhere.** An information-free term makes the board slightly
worse on average, at every position — which is what a term carrying nothing should do. Nothing
is negative on average, so `audible#87`'s "noise HELPS at tight end" has no support once the
draw is repeated.

### where the single published draw actually sat

Ties are counted rather than swallowed, because at QB the fit declines the noise knob outright
in many draws and they all sit at exactly +0.000:

    board  legacy +0.364   17 below, 0 tied, 23 above of 40    typical
    QB     legacy +0.000    0 below, 14 tied, 26 above of 40   tied at the minimum
    RB     legacy +0.113   22 below, 0 tied, 18 above of 40    typical
    WR     legacy -0.620    4 below, 0 tied, 36 above of 40    near-extreme
    TE     legacy -1.083    0 below, 0 tied, 40 above of 40    OUTSIDE the range of all 40

**This is the whole failure in one table.** The salt `audible#86` and `#87` published was
*typical board-wide and typical at RB*, and *outside the entire empirical support at TE*. So the
board-wide number looked unremarkable while the positional conclusions built on it were extreme.
A referee that checked only board-wide would have reported nothing amiss.

(An earlier version of this table reported "rank 1/24 at QB", which was an artefact of counting
ties as though they were above. Corrected here.)

### G2 — resampling the salt widens the interval, and the old mechanism resolves nothing

The term under test is **another information-free draw** — known to carry nothing, so an honest
interval must contain zero.

    locus  conditional width  unconditional width  widened   one-draw verdict
    board            1.431              2.438       1.70x    RESOLVED BEATS FLOOR
    QB               0.000              0.915         n/a    not resolved
    RB               0.000              0.663         n/a    not resolved
    WR               1.792              2.535       1.42x    not resolved
    TE               1.559              1.950       1.25x    RESOLVED WORSE THAN FLOOR

**The broken mechanism resolves a term guaranteed to be information-free, at two of five loci,
in both directions.** The distribution says "not resolved" at all five, correctly. At QB and RB
both draws have all-zero deltas — the fit declines the noise knob — so the conditional
difference is identically zero and the ratio is undefined.

---

## TASK 3 — re-adjudication, interval against interval

Expected loci were stated before any number was computed (G7) and are in `PLAN` at the top of
`s5_adjudicate.py`. Every figure is `signal − floor` with the season AND the salt resampled
together.

    signal              locus  signal delta   difference [2.5%, 97.5%]      bootstrap
    snap_share            RB        +0.314   +0.210 [-0.231, +0.568]   not resolved
                          WR        +0.252   +0.202 [-1.133, +1.502]   not resolved
                          TE        +0.286   +0.090 [-0.794, +1.138]   not resolved
    adp_gap               QB        +0.216   -0.003 [-0.768, +0.446]   not resolved
                          RB        -0.112   -0.216 [-0.719, +0.136]   not resolved
                          WR        -0.181   -0.231 [-1.651, +1.194]   not resolved
                          TE        -0.253   -0.450 [-1.423, +0.581]   not resolved
    draft_round           RB        +0.109   +0.005 [-0.457, +0.334]   not resolved
    (rookies only)        WR        +0.032   -0.018 [-1.421, +1.453]   not resolved
                          TE        +0.147   -0.049 [-1.018, +1.033]   not resolved
    ngs_separation        WR        -0.874   -0.924 [-2.401, +0.593]   not resolved
    ngs_rush_eff          RB        +0.087   -0.017 [-0.466, +0.279]   not resolved
    ngs_time_to_throw     QB        +0.669   +0.449 [-0.252, +1.547]   not resolved
    contract              QB        +0.000   -0.219 [-0.915, +0.000]   not resolved
                          RB        +0.177   +0.073 [-0.455, +0.479]   not resolved
                          WR        +0.469   +0.418 [-0.837, +1.632]   not resolved
                          TE        +0.787   +0.591 [-0.376, +1.686]   not resolved
    availability       board        +0.813   +0.464 [-0.775, +2.001]   not resolved

Positive is worse. **Eighteen loci, and the bootstrap resolves none of them — but see G9: that
bootstrap is a 0.5% test wearing a 5% label, and the calibrated test resolves two.**

### old decision beside new (G6)

    snap share        REVERTED        -> NOT RESOLVED
    adp gap           REVERTED        -> NOT RESOLVED
    rookie capital    REVERTED        -> NOT RESOLVED
    ngs_rush_eff      REVERTED        -> NOT RESOLVED
    ngs_time_to_throw REVERTED        -> RESOLVED WORSE at a calibrated 5% (p = 0.049)
    contract          REVERTED        -> NOT RESOLVED
    ngs_separation    UNRESOLVED      -> RESOLVED BETTER at a calibrated 5% (p = 0.049)
    availability      NEVER MEASURED  -> NOT RESOLVED (first real measurement)

**Two of eight change materially.** The other six move from REVERTED — which asserts a term was
tested and failed — to NOT RESOLVED, which asserts the harness cannot tell. Six seasons never
had the power to support the first claim.

### INJECTION 1 — what the single draw would have decided

Five loci get a **different disposition**, and every one is a **false resolution**:

    snap_share@RB   draft_round@WR   ngs_time_to_throw@QB   contract@WR   contract@TE
    all five:  one draw says RESOLVED WORSE THAN FLOOR;  the distribution says not resolved

Interval widths change by **0.98x to 2.90x** once the salt is resampled — note that
`contract@TE` got marginally *narrower*, so "resampling the salt widens the interval" is a
tendency and not a law. On this set the old mechanism manufactures resolution at 5 of 18 loci,
**28%**, all in the same direction.

### INJECTION 4 — the dilution, per signal

    ngs_separation     WR  -0.874 at locus vs +0.287 board-wide   sign FLIPS
    snap_share         RB  +0.314 at locus vs -0.539 board-wide   sign FLIPS
    adp_gap            QB  +0.216 at locus vs -0.457 board-wide   sign FLIPS
    ngs_time_to_throw  QB  +0.669 at locus vs +0.579 board-wide
    ngs_rush_eff       RB  +0.087 at locus vs +0.027 board-wide
    contract           QB  +0.000 at locus vs +0.489 board-wide

**Three times the board-wide figure carries the opposite sign to the locus figure.** Separation
reads as a harm board-wide and a benefit at wide receiver; snap share reads as a benefit
board-wide and a harm at running back. Averaging a positional effect across four positions does
not merely weaken it — it can invert it.

### `availability` — first real measurement, and a refuted prediction with a fixable cause

    board  +0.813 [+0.150, +1.969]   floor +0.348   difference +0.464, not resolved
    fitted lambda 2020:0.0  2021:-0.1  2022:+0.05  2024:+0.1  2025:-0.1   SIGN FLIPS

**The structural prediction failed, and then turned out to be right.** `audible#87` predicted,
and this session restated, that a value constant within a position cannot reorder that position,
so every per-position figure must be exactly +0.000. Measured: RB +0.159, QB −0.036, WR −0.028,
TE +0.0004.

The premise is exactly right and the metric is what breaks it:

    2020  QB order_same=True pool  9->11     2024  QB order_same=True pool 10->12
          RB order_same=True pool 54->58           RB order_same=True pool 52->43
          WR order_same=True pool 44->37           WR order_same=True pool 47->53
          TE order_same=True pool 21->22           TE order_same=True pool 19->20
    2021, 2022, 2025  pool unchanged everywhere -> per-position exactly +0.0000

**The within-position order never changes — not once, in any position, in any season.** What
changes is POOL MEMBERSHIP, and `score_board.per_position` scores each position over its slice
of the **global** top-128. Scoring instead over a **position-local** top-32:

    2020  QB +0.0000  RB +0.0000  WR +0.0000  TE +0.0000
    2021  QB +0.0000  RB +0.0000  WR +0.0000  TE +0.0000
    2022  QB +0.0000  RB +0.0000  WR +0.0000  TE +0.0000
    2024  QB +0.0000  RB +0.0000  WR +0.0000  TE +0.0000
    2025  QB +0.0000  RB +0.0000  WR +0.0000  TE +0.0000

**Exactly zero everywhere, and it cannot depend on the choice of N**, because the within-position
order is provably unchanged so a position-local top-N is unchanged for any N. **The prediction
was right; `score_board.per_position` is the defect.** A per-position score should be computed
over a position-local pool. That is a change to the metric affecting every per-position number
in `audible#84` through `#87`, so it is reported here and not made mid-session.

Same shape as the `shrink` finding: **the per-position metric is not independent of the
cross-position ordering**, and a "locus" is not the clean separation three sessions assumed.

---

## TASK 4 — `ngs_separation`: resolved, and resting on two seasons

    WR   signal -0.874 [-1.957, +0.117]   floor +0.050 [-1.113, +1.290]
         bootstrap difference -0.924 [-2.401, +0.593]   not resolved
         reference-set p = 0.049 over 40 draws          RESOLVED at a calibrated 5%
         fitted lambda +0.05 in ALL SIX FOLDS -- the only term whose weight never flips

    per season  2019:-0.82  2020:+0.20  2021:-2.79  2022:-0.26  2024:+0.73  2025:-2.30

**2021 and 2025 carry 83% of it.** The negative seasons sum to −6.17 and those two are −5.09.

    dropping 2021        signal -0.491   difference -0.581 [-2.102, +0.943]
    dropping 2025        signal -0.588   difference -0.677 [-2.142, +0.854]
    dropping both        signal -0.038   difference -0.186 [-1.733, +1.317]

Without those two seasons the effect is **−0.038 — nothing at all.**

**DISPOSITION: RESOLVED at a calibrated 5%, and fragile.** It is the largest effect this project
has measured, the only fitted weight stable across all six folds, WR-specific as its mechanism
requires, and its p sits at `2/41 = 0.0488` — the floor of what 40 draws can express, meaning it
is more extreme than every information-free draw. It also rests on two seasons out of six. Both
halves are true and neither cancels the other. More draws would sharpen the p; only more seasons
would settle the fragility, and there are none.

### the window cannot be extended, and the board is why

    2016, 2017, 2018   board FAIL: espn is excluded    realised FAIL: outcomes not pinned
    2019               board 481   realised 572   ngs_separation 125
    2023               board FAIL: espn 2023 excluded  realised 577

ESPN is a seven-season vintage source beginning 2019 and outcomes are pinned 2019–2025. NGS
coverage back to 2016 is irrelevant: those seasons have no board and no truth to score against.
**Six seasons is a hard ceiling on the LOSO's degrees of freedom, set by the board source.**

---

## G9 — POWER, and the correction the review forced

The first version of this document reported "eighteen loci, not one resolves" and called it the
session's result. That was true of the bootstrap referee and **misleading**, because the referee
had never been calibrated.

**A referee's own false-resolution rate is measurable**, and it is the check `audible#86` and
`#87` never ran. Every floor draw is information-free, so adjudicating draw *j* against the
other 39 is a test whose null is true:

    locus  resolved/40   rate   reference-set p:  min    5th   50th
    board        0/40    0.0%                   0.050  0.050  0.650
    QB           0/40    0.0%                   0.050  0.100  0.700
    RB           0/40    0.0%                   0.050  0.050  0.950
    WR           1/40    2.5%                   0.050  0.050  0.550
    TE           0/40    0.0%                   0.050  0.050  0.550

**1 of 200 = 0.5% at a nominal 5%.** The bootstrap referee is roughly ten times stricter than
its label. It is not a conservative 5% test; it is a 0.5% test, and "nothing resolves" under it
is a much weaker statement than it appears.

The **reference-set p-value** needs no calibration argument — its null distribution is uniform
on the draws by construction, and with K=40 its floor is 0.0488, just inside 5%:

    ngs_separation@WR       p 0.049   <== RESOLVED at a calibrated 5%
    ngs_time_to_throw@QB    p 0.049   <== RESOLVED at a calibrated 5%
    adp_gap@RB              p 0.098
    contract@TE             p 0.098
    snap_share@RB           p 0.195
    availability@board      p 0.195
    ...
    adp_gap@QB              p 1.000

**Two of eighteen resolve.** `ngs_separation` at wide receiver is the first calibrated
resolution this project has produced, in the direction of improvement. `ngs_time_to_throw` at
quarterback resolves in the direction of harm, which is also information: it is the term the
board should stop being nudged by.

### so: is resolution possible at six seasons?

**Marginally, and only at the extreme.** Both resolutions sit at the floor of what 40 draws can
express, so they say "more extreme than 40 information-free terms" and not "p = 0.001". The
bar remains high:

    locus   difference half-width   what an effect must exceed
    RB              0.38 - 0.48                  ~0.4
    QB              0.49 - 0.90                  ~0.7
    TE              0.92 - 0.99                  ~1.0
    WR              1.12 - 1.40                  ~1.2

On a consistent scale, `ngs_separation`'s difference of −0.924 against a half-width of 1.497 is
short by 1.62x under the bootstrap, and clears the reference-set test only because it is more
extreme than all 40 draws. Three constraints multiply, and only one is fixable:

1. **Six seasons is a hard ceiling** — the board source sets it and it cannot move.
2. **The floor's own sd is 0.14 to 0.50**, comparable to every effect measured.
3. **The season is the resampling unit**, and six clusters is very few.

What is fixable: **the number of draws**. K=40 buys a 5% test; K=79 would buy 2.5%. That is
cheap — 13 seconds a draw — and it is the only lever this harness has left.

What this rules out: expecting a *comfortable* resolution from one scalar-weighted signal at a
time. What it does not rule out is what the standing goal actually asks for — a transform that
changes the ordering's shape rather than nudging it with a scalar weight.

---

## WHAT THE ADVERSARIAL REVIEW (G15) OVERTURNED

The review ran foreground, one agent. It changed the headline and found six real defects.

1. **The headline.** "Nothing resolves" was reported without ever calibrating the referee.
   Measured, it fires 0.5% of the time under a true null at a nominal 5%. Calibrated, **two of
   eighteen loci resolve.** The review also priced the alternative I might have been tempted by
   — comparing against the floor's *mean* with `var/24` — and showed it falsely resolves an
   information-free term **35%** of the time. So the choice of null was right and the
   *threshold* was wrong, which is a much better place to be wrong.
2. **24 draws could not express a 5% test.** Floor `2/(K+1)` = 0.080. Redrawn at K=40.
3. **`s5_gate.py` printed a hardcoded falsehood** — `n_moving = 0` was assigned and never
   updated, so the committed output read "shrink moves an ordering in 0/6 seasons" directly
   beneath its own data showing 377 and 353. Fixed, and `shrink` now goes through the real gate.
4. **G4 was satisfiable after all.** I reported it as failed and refused to tune the threshold.
   Refusing to tune was right; concluding no honest condition existed was wrong. Condition 4
   names the mechanism and rejects `shrink` 0/6 while every real term passes 6/6.
5. **`s5-floor.out` was stale** and contradicted the document; the per-position `availability`
   figures came from an uncommitted run. Both fixed — every published number now has committed
   output behind it.
6. **Four number errors**: "1.06x to 2.90x" was really 0.98x to 2.90x (`contract@TE` narrowed);
   the WR power minimum was 1.118 not 1.20; the QB legacy "rank 1/24" was a tie artefact with 14
   draws sharing +0.000; and "eleven runs across five sessions" was a figure with no artefact
   behind it and has been removed.

The review also proved the **position-local pool** counterfactual that turned a refuted
prediction into a located defect in `score_board`, and found that `MIN_SD_REL` is redundant
(`distinct <= 1` reproduces all 20 skips). One finding is recorded and **not** acted on:
`sim/search.py::_season_inputs` builds `position` by `.update()` across espn/ffa/sleeper so the
last arm wins, and 1–7 players a season are bucketed differently there than in `sim/signals.py`.
**A board built through `sim/search.py` is not the board built through `sim/signals.py`.** That
is a live inconsistency between the two halves of the harness, it predates this session, and it
is the first thing the next one should look at.
