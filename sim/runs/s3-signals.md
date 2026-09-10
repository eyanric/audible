# S3 — every avenue

`audible#85` searched 4,000 boards over 8 knobs; the winner was 2.522 RWRE worse on a holdout.
Reweighting known information does not work. This session measures WHERE the error is, then
tests the signals that measurement ranks.

Appended as each result lands.

---

## HANDOFF PREMISES REFUTED BEFORE ANY WORK STARTED

The handoff lists Task 1 predictors as available. Four were not:

    ff_opportunity     ONLY 2025 pinned, not all seasons
    depth_chart_slots  NOT pinned at all
    draft_picks        ONLY 2026 pinned
    schedules          ONLY 2026 pinned
    snap counts        NOT pinned at all

All four were fetched into the gitignored `data/sim-cache/nflverse/` for this session --
`ff_opportunity` 2018-2025 (47,282 rows), `draft_picks` 1980-2026, `snap_counts` 2018-2025
(205,354 rows), `depth_charts` 2018-2025 (813,157 rows, and only by fetching per season: a
whole-range call raises `TypeError: '<' not supported between instances of 'int' and
'NoneType'` inside nflreadpy).

**And the FFA files are far richer than the handoff describes.** `projections_<season>_wk0.csv`
carries `age`, `experience`, `sd_pts`, `dropoff`, `floor`, `ceiling`, `uncertainty`, `tier` and
`adp` -- vintage, per season. So Task 2's 2c (age curves), 2d (projection uncertainty) and 2f
(ADP gap) need no new data at all; they were already on disk.

**A coverage limit worth stating.** The FFA projections file is a TOP-N export, not a full pool:
72 RB, 72 WR, 37 QB, 36 TE in 2022, plus IDP and K/DST. So FFA-derived predictors exist for
roughly the draftable 217 per season, which is 42% of ESPN's 491-player pool. That is not a
broken join -- it is what FFA publishes -- and it is the population the board is actually
graded on, so the diagnostic runs on complete cases and says so.

---

## TASK 1 — the residual diagnostic

`residual = realised_rank - projected_rank`, within position, within season. **Positive means
he finished WORSE than projected (a bust); negative means he outperformed (a sleeper).**

Thirteen predictors, every one knowable before the season. Source is `espn` (production's).
Seasons 2019-2022 and 2024-2025 -- ESPN has no 2023 and `arms.load` refuses it, which is G9
firing rather than a gap.

### univariate variance explained, per position, pooled across seasons

    QB   adp_gap 10.9%  ... (see ranking below)
    RB   career_outlier 1.83%  spread_rel 1.00%  sd_rel 0.74%
    WR   adp_gap 10.07%  experience 1.27%  age 1.04%  prior_ay_share 0.72%
    TE   prior_snap_share 9.53%  prior_games 1.98%  prior_tgt_share 1.87%

### sign stability across seasons -- the filter that matters

A coefficient that flips sign is noise whatever its t-statistic.

    STABLE (100% sign agreement)
      adp_gap           ------
      prior_tgt_share   +++++
      prior_ay_share    +++++
      prior_snap_share  ++++++
      draft_round       ------

    UNSTABLE, discarded
      td_oe             -++--+   50%
      dropoff           ----++   67%
      career_outlier    +-++     75%
      prior_games       +-+++    80%
      age / experience / sd_rel / spread_rel   83%

**`td_oe` -- touchdowns over expected -- is the handoff's 2a, called "the strongest prior". It
ranks TWELFTH of thirteen at 0.29% mean univariate R2, and its sign flips half the time.**
That is the clearest premise refutation in the session, and it is exactly what the diagnostic
exists to catch: a mechanism that is compelling in prose and absent in the data.

### THE CEILING — and parsimony is the whole story

All thirteen predictors together, fit on 2019-2022 and scored on 2024-2025:

    position   in-sample    walk-forward
    QB           20.37%        -154.97%
    RB            9.49%         -36.83%
    WR           16.01%          +1.58%
    TE           21.94%        -103.77%

**A negative R2 means the model is worse than predicting the mean.** Thirteen parameters on
roughly a hundred complete cases per position does not describe the data, it memorises it.

Cutting parameters fixes it:

    model                     QB       RB       WR       TE
    all 13                -154.97%  -36.83%   +1.58% -103.77%
    sign-stable 5            -0.45%   -4.16%   +5.73%   +9.05%
    stable non-circular 4    -5.97%   -1.09%   +9.14%   +2.44%
    top-3 by R2              +6.44%   -1.67%   +4.46%  -11.66%
    adp_gap alone           +14.94%   +4.30%   +4.00%  -16.53%
    prior_snap alone         +0.48%   +3.49%   +7.24%   +2.45%

**`prior_snap_share` alone is the only predictor positive in all four positions out of
sample** -- 0.5% to 7.2%, one parameter, non-circular.

`adp_gap` is larger at QB and RB but is **circular by construction**: ADP is partly derived from
the same projections the residual is computed against, so it is measuring how far the board sits
from a market that already read the board. It is reported and is not treated as new information.

### THE ANSWER TO THE QUESTION THE HANDOFF ASKED

**The ceiling for an honest, non-circular signal is roughly 3-7% of residual variance, with one
parameter, and it goes NEGATIVE as soon as parameters are added.**

That is the most important number here. It says the board is near its INFORMATION limit rather
than its weighting limit, and it bounds what every iteration below can possibly achieve. A
signal explaining 3% of residual variance cannot move a rank metric much, and `audible#84`
already demonstrated the stronger version of that: `prior_tgt_share` sits at 1.41% here and
bought exactly zero board improvement when it was actually tested.

### INJECTION 7 — the diagnostic is genuinely walk-forward

    WR 2024, fit and scored on itself:  R2 37.61%
    WR walk-forward (fit 2019-22):      R2  1.58%

A twenty-four-fold inflation. Fitting on the season you score against is not a small effect,
and the split is doing real work.

### ranking for Task 2, by mean univariate R2 across positions

     1  adp_gap            5.68%   CIRCULAR -- reported, not trusted
     2  prior_snap_share   2.66%   sign-stable, positive OOS everywhere
     3  age                1.49%
     4  prior_tgt_share    1.41%   already measured at zero by audible#84
     5  experience         1.24%
     6  draft_round        1.09%   sign-stable
     7  prior_ay_share     0.78%
     8  spread_rel         0.65%
     9  prior_games        0.61%
    10  sd_rel             0.57%
    11  career_outlier     0.50%
    12  td_oe              0.29%   the handoff's "strongest prior"
    13  dropoff            0.22%

**This ranking replaces the handoff's ordering for Task 2.** 2a goes last, not first.
