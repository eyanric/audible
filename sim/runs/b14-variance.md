# B14 — make the comparisons resolvable

Base `main` at 714a94ea. Branch `feat/variance-reduction`.
Nothing is adopted. The estimator was built, measured and
refused. This records why, in enough detail that a later
session does not rebuild it.

## VERDICT

**NONE.** No comparison is now resolvable that was not.

The adjustment would have bought between 2 and 11
comparisons depending on which set is counted, and every
one of them is void: the adjusted interval covers the
wrong estimand, and the rule for adopting it manufactures
significance out of noise 23% of the time.

## Task 1 — the covariate does correlate, and it does not
## matter

Pre-registered primary in `b14-plan.md`, committed before
any adjusted interval existed: `ceiling_minus_adp`.

Correlation with the paired differences, production board
(b13), five season means, `1 - rho^2` in brackets:

```
                      ffc_12       mfl_12       mfl_8
  real - adp        -0.02[1.00]  -0.39[0.85]  -0.13[0.98]
  real - points_gr  -0.22[0.95]  -0.82[0.33]  -0.87[0.24]
  real - ffa_basel  -0.40[0.84]  -0.77[0.41]  -0.90[0.19]
  real - transform  -0.49[0.76]  -0.88[0.22]  -0.95[0.10]
  transform - ffab  +0.10[0.99]  +0.29[0.91]  +0.18[0.97]
  bot (level)       -0.45[0.80]  +0.44[0.81]  -0.42[0.82]
```

Alternatives, `real - adp` / `real - ffa_baseline` /
`real - transform`:

```
  adp_level      -0.36 -0.60 -0.67   ffc_12
                 -0.52 -0.09 +0.01   mfl_12
                 -0.64 +0.08 +0.22   mfl_8
  season_points  -0.25 -0.51 -0.58   ffc_12
                 -0.73 -0.69 -0.77   mfl_12
                 -0.63 -0.97 -0.95   mfl_8
```

`season_points` beats the primary on `real - adp` in two
of three markets. It is NOT promoted; the pre-registration
fixed the primary and swapping it after seeing this is the
thing that rule exists to prevent.

THE HANDOFF'S PREDICTED FAILURE MODE WAS THE OPPOSITE OF
WHAT HAPPENED. It expected a covariate correlating with
the LEVELS but not the DIFFERENCES. In fact it correlates
with exactly the differences that fail to resolve and not
at all with `transform - ffa_baseline`, the one that
already does. That is the useful direction — and it is
still not enough, for reasons that have nothing to do with
rho.

`real - adp`, the comparison that decides whether any of
this is evidence, correlates at -0.02 / -0.39 / -0.13 and
is below break-even in every market on every covariate.

## The break-even, twice wrong before it was right

`b14-plan.md` pre-registered `|rho| > 0.489`. That is
WRONG and wrong in the adopting direction: it used the
ratio of t quantiles alone and omitted the inflation in
the residual variance estimate at `k-2` df.

```
  s_e^2 = s_Y^2 (1 - rho^2)(k-1)/(k-2)
  ratio = t(k-2)/t(k-1) * sqrt((1-rho^2)(k-1)/(k-2))
  k = 5:  1.3235 * sqrt(1 - rho^2)  ->  |rho| > 0.655
```

Bisecting the actual crossing on constructed data lands at
0.65511765 against 0.655118 from the formula.

THEN IT WAS SHIPPED AS A CONSTANT, which an adversarial
review broke at k = 4. It is not a constant:

```
  k        4      5      6      7     10
  |rho|  .797   .655   .560   .495   .380
```

At k = 4 a comparison at rho 0.790 was marked as clearing
while coming out 1.5% wider — the identical error the
pre-registration made, relocated one level up. Reachable:
`b4-transform` is four seasons and the walk-forward splits
are two and three. `adjust.break_even_rho(k)` now derives
it.

## Task 2 — the premise is refuted. It was already paired.

The handoff says `real - adp` "spans zero because it is
not paired that way". It is paired that way. Both it and
`transform - ffa_baseline` go through `runner._compare` ->
`_paired_difference`, which joins on (season, seed) and
clusters on season.

Verified in all three markets on both checkpoint sets:
300 units each, |A| = |B| = intersection, no orphans,
mean/lo/hi reproducing the committed artifacts to 1e-6.

WHY ONE RESOLVES AND THE OTHER DOES NOT, after two wrong
answers. "The season shock cancels because the arms share
a board" was refuted — in ffc_12 both comparisons have
nearly the same between-season share and the separation is
effect size. "Pairing needs comparable season spread" was
refuted by its own gate, 0.961 against 0.974, backwards.

What survives is the direct measurement — how much the
paired difference's season spread beats two independent
arms', `sd(diff)/sqrt(sdL^2 + sdR^2)`:

```
  b10 market       real - adp   transform - ffa_baseline
    ffc_12            1.12x            0.24x
    mfl_12            0.98x            0.36x
    mfl_8             0.84x            0.26x
  b13 production
    ffc_12            1.03x            0.24x
    mfl_12            0.90x            0.36x
    mfl_8             0.95x            0.26x
```

Pairing removes about three quarters of the season spread
from one and NOTHING from the other — in ffc_12 it makes
it worse. Six cells, no overlap. Per-unit between-arm
correlation says the same: +0.63..+0.69 against
+0.32..+0.44.

That answers the common-random-numbers premise. The arms
ALREADY run on common random numbers. What they do not
share is CONDITIONS: the room is reactive, so two arms
that differ at pick 3 face different opponents from pick 4
on, and `real` is the full stack against a ten-line
baseline. `seat.run_arm`'s docstring has measured that
since B2.

Injection 4 confirms pairing is doing something and that
it is small: unpaired `real - adp` in ffc_12 is
[-77.62, +176.32] against paired [-61.86, +160.55], a 12%
width reduction.

## Task 3 — THE ESTIMATOR MUST NOT MANUFACTURE
## SIGNIFICANCE, and it does

This is where the session ends.

### The classical control variate is unavailable

It subtracts `beta * (W - E[W])` and needs `E[W]` known a
priori. Five seasons, no sixth. Substituting the sample
mean makes the correction identically zero, so the point
estimate cannot move.

CONSEQUENCE FOR THE HANDOFF'S OWN INJECTION 3 — "fix beta
at a large wrong value, the point estimate moves and G6
fires" — IT CANNOT FIRE. Demonstrated for beta = 0, 50 and
-1000: the estimate does not move by 1e-9. G6 is satisfied
by arithmetic. **A G6 pass is not evidence of anything**
and this was pre-registered before the numbers existed.

### What was built instead, and why it is void

The conditional (ANCOVA) reading: same point estimate,
interval from the residual spread about a fitted season
slope, paying one degree of freedom. The algebra is right
— `Var(alpha_hat) = sigma_e^2/k` exactly for a centred
regressor, confirmed at 200k replications, 4.985 against
5.000 predicted.

It is an exact 95% interval for `E[Y | W = Wbar]`. The
repo reports `E[Y]`, the mean over seasons. The missing
term is the same one that killed the control variate:

```
  Ybar - E[Y] = beta (Wbar - E[W]) + ebar
```

and the adjusted half-width prices only `ebar`. Measured
coverage of a nominal 95% interval, two independent
reviews at 60k and 100k replications, k = 5:

```
  |rho|   0.00  0.45  0.50  0.655  0.71  0.80  0.90  0.95  0.98
  covers  .950  .935  .929  .904   .891  .848  .740  .607  .422
```

**Coverage falls monotonically in exactly the quantity the
adoption rule selects on.** At the break-even threshold a
nominal 95% interval covers 90%. At the correlations the
headline comparisons actually show it covers 40-75%.

### And the adoption rule adds a second layer

`rho` is estimated from the same five points as the
interval. Against a covariate carrying ZERO information:

```
  clears the gate            23.1% of the time
  median width when adopted  0.818x (18% narrower)
  coverage when adopted      87.7%
  false-positive rate        12.4% against a true null
  best of three covariates   54.4% clears, 86.3% covers,
                             13.7% false positive
```

Pre-registering the threshold does not help. `b14-plan.md`
fixed the threshold, not the outcome.

### G4 passes and does not rescue anything

`bot` is the true null — `simulate_draft` with no chooser,
eight seats running identical code. Searched exhaustively
over 3 markets x 3 lineup policies x 3 covariates x 2
checkpoint sets = 54 combinations: **zero flips.** Every
`bot` width ratio is above 1; the adjustment strictly
widens the null control.

BUT IT PASSES BY CORRELATION, NOT BY CONSTRUCTION.
`bot`'s |rho| never exceeds 0.548 in any of the 54 cells,
below break-even. A null control whose covariate happened
to correlate would not be protected by anything in the
method. That is why G4 green does not license adoption,
and it is why the coverage gate had to be written.

### The covariate is one of the comparisons

`ceiling_minus_adp` IS `runner._COMPARISONS`'
`hindsight_board - adp`. Adjusting that comparison by that
covariate is a regression of a response on itself: the
first version returned rho = 1.000000 and a **zero-width
95% interval** in all three markets, declared resolvable,
and nothing refused it. Now refused on the residual rather
than on the name, so any collinear covariate is caught
however it was built.

## Task 4 — both estimators, side by side

Full tally, production board, 3 markets x 3 lineup
policies x 17 comparisons = 153 cells:

```
  field                   wider  narrower  destroyed  bought
  advantage                  24        27          4       6
  advantage_season_mean      24        27          3       4
  advantage_realised         25        26          0       1
  TOTAL                      73        80          7      11
```

`real - adp` is WIDER in all nine market x policy cells
(1.323 / 1.219 / 1.311 under the prior lineup).

**It destroys seven previously-resolvable results**,
including `real_minus_adp` itself in ffc_12 under the
oracle lineup, [+7.25, +112.39] -> [-9.14, +128.79].

The narrowings do not survive leave-one-season-out. The
strongest, `ffc_12 real - audible_transform` at rho
-0.983, adj [+31.4, +75.1]: drop 2022 and it is
[-3.4, +77.3]; drop 2023 and it is [-8.2, +72.7]. Two of
five seasons carry it. `mfl_12
transform_under_perfect_foresight` and `mfl_8
points_minus_adp` each lose it on three of five drops.

And the search space is 153 wide. Picking the narrowings
out of it is the multiplicity the selection measurement
above prices.

### Which comparisons are now resolvable that were not

**NONE.** Stated as plainly as a success would be.

## What is shipped

`sim/adjust.py`, wired to nothing, with the refutation in
its docstring and `NOT_FOR_REPORTING` on the module.
`report()` is the only sanctioned renderer and it prints
the reported interval, the conditional one labelled as a
different estimand, and the coverage warning.

`sim/test_g_b14.py`, 16 gates, whose purpose is to stop
re-adoption. The deciding one asserts the coverage
FAILURE.

## Gate holes this session opened and closed

The first version of the gate file had 11 tests and an
adversarial review passed two mutations through all of
them:

  * `adjust()` returning the unadjusted interval always —
    every arithmetic assertion read `width_ratio`, which
    is computed independently of `adj_lo`/`adj_hi`, and
    nothing tied them together.
  * `covariate_table` returning one table for every name —
    the `ValueError` guard was tested and the payload was
    not, so a version ignoring `name` was green.

Both closed, and six mutations now caught: those two,
dropping the df penalty, flipping beta's sign, freezing
break-even at 0.655, and removing the self-adjustment
guard.

## Other defects found and fixed

  * `variance_reduction` held `1 - rho^2`, the variance
    RETAINED. A covariate absorbing 96.6% reported 0.034.
    Renamed `variance_retained`.
  * `_fisher`'s docstring worked its example wrong:
    `_fisher(-0.95, 5)` is [-0.997, -0.419], not the
    "-0.999 to -0.31" claimed.
  * `test_i1`'s comment said five-point noise implies
    `1 - rho^2` near 0.8. It is 0.75.
  * `adjust.paired` uses `r[field]` where
    `_paired_difference` uses `.get(field, 0.0)`. Kept
    deliberately and now documented: production would
    quietly report a missing unit as a tie, and an
    analysis that does the same is worse than one that
    stops. No gap exists today — 0 missing values across
    3,900 rows x 6 checkpoints.
  * `covariate_table` builds every covariate from
    `advantage`, the prior lineup, whatever policy is
    being adjusted. Documented, not fixed.

## Standing caveat, carried forward

Pairing reduces variance; it does not remove bias.
`real` is the full stack, so its comparisons carry the
room's biases including `ffc_12` releasing the first
quarterback 5.76 picks early — cause unexplained after
three refuted hypotheses in `b10-leak.md`.

## What would actually work

Not measured here, so stated as a direction and not a
result. The coverage failure comes from `Wbar` not being
`E[W]`. Anything that supplies `E[W]` from OUTSIDE the
five seasons being averaged would restore the classical
estimator — more pinned seasons, or a covariate whose
population mean is known by construction rather than
estimated. Within five seasons and no sixth, the
between-season component is what `audible#76` said it was.
That conclusion is unchanged, and now it has a measurement
under it rather than an assumption.
