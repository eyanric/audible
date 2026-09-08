# B14 pre-registration, committed before any adjusted interval

Base `main` at 714a94ea. Written and committed BEFORE computing a
single adjusted interval, so G2 is satisfied by commit order rather
than by assertion.

## The primary covariate

**`ceiling_minus_adp`** — per season, the mean of
`hindsight_board.advantage` minus the mean of `adp.advantage` over
that season's units. It is the handoff's own candidate: how much
value was available to be found that year.

Two alternatives are measured and reported beside it. Neither can
be promoted after the fact.

  * `adp_level` — the `adp` arm's own season-mean advantage.
  * `season_points` — the mean `points_for` over every arm and seed
    in that season, i.e. the season's scoring level.

## The decision rule, fixed now

A covariate is only worth adopting if it narrows the interval on the
DIFFERENCES, not on the levels. Pairing may already have removed the
season shock from the differences that resolve, which is the likely
failure mode and the reason Task 1 exists.

**THE BREAK-EVEN IS NOT ZERO AND IT IS NOT SMALL.** These intervals
are clustered on five season means with a t quantile on 4 df.
Estimating one slope from those same five points costs a degree of
freedom, so the quantile goes 2.776 -> 3.182, a factor of 1.146. The
residual variance must therefore fall by more than that squared just
to break even:

    adopt only if  1 - rho^2  <  0.761
    equivalently   |rho|      >  0.489

on the paired differences, in a market, before any adjusted interval
is called narrower than its unadjusted counterpart.

## What this session will NOT claim

The classical control-variate estimator subtracts `beta * (W - E[W])`
and requires **E[W] to be known a priori**. It is not known here:
there are five seasons and no sixth to estimate it from. Substituting
the sample mean makes the correction identically zero at the mean, so
the adjusted point estimate is the unadjusted one BY CONSTRUCTION and
G6 is satisfied trivially rather than informatively. That is stated
here in advance so that a G6 pass is not later read as evidence the
covariate is sound.

What remains available is a regression-adjusted (ANCOVA) interval:
the same point estimate, with the interval built from the residual
spread about the fitted season slope, paying one degree of freedom.
That is what will be reported if Task 1 clears the bar above, and it
will be named that rather than called a control variate.

## Stop condition

If `rho` on the paired differences is below the break-even in the
markets that matter, the covariate does nothing, the session reports
that as its finding, and no estimator is adopted.
