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

---

## G6 — every term is shown to move an ordering BEFORE it is measured

`audible#85` shipped a `shrink` knob that was provably inert. This is the gate that catches it.
Players displaced from the 2022 board at lambda = 0.10:

    noise 456   draft_round 459   snap_share 453   td_oe 453
    target_share 434   uncertainty 434   adp_gap 429   age 394

    shrink s=0.30 ................................ 0   REFUSED

**Injection 3 fires:** the uniform positional shrink `audible#85` searched over displaces
exactly nobody, because scaling every player at a position by the same factor scales VORP
uniformly and leaves the order unchanged. G6 would have refused it before a single measurement.

---

## THE NOISE FLOOR, measured in this regime

A sha256 of player and season, information-free by construction, tuned by the same
leave-one-season-out procedure as every signal:

    2019 +0.825   2020 +1.119   2021 -0.039   2022 +0.000
    2024 +0.000   2025 +0.281
    MEAN +0.364

**Noise makes the board 0.364 WORSE on average here**, where in `audible#85`'s two-season select
split the same hash bought +2.317 of apparent improvement. That difference is the procedure, not
the hash: fitting on five seasons and testing on the sixth is far harder to overfit than fitting
on two and testing on two. The rotated holdout is doing real work.

---

## ITERATION 1 — prior-season snap share (Task 1's top honest signal): REVERTED

Mechanism, committed before running: snap share is the closest thing to a pure workload measure,
and Task 1 ranked it the only predictor positive in all four positions out of sample.

    season   base -> treated   delta    lambda
    2019   18.402 -> 17.629   -0.773    +0.05
    2020   23.406 -> 23.154   -0.252    +0.05
    2021   24.396 -> 21.707   -2.689    +0.05
    2022   22.892 -> 23.169   +0.278    +0.05
    2024   25.566 -> 25.539   -0.027    +0.05
    2025   19.891 -> 20.124   +0.233    +0.05

    MEAN -0.539, and it BEATS the noise floor of +0.364

Every one of the six folds independently chose lambda = +0.05, the smallest non-zero weight in
the grid. That consistency is the strongest thing about the result.

**But it does not survive the per-player test.** Paired over players across all six seasons:

    snap_share  -0.072 [-0.307, +0.162]  n=751   NOT RESOLVED

And the season-level mean is one season:

    mean across all six      -0.539
    mean excluding 2021      -0.108

2021 alone contributes -2.689 of a -0.539 average. Strip it and the effect is a tenth of an
RWRE, well inside the interval.

**DISPOSITION: REVERTED.** It beats the noise floor on the season-mean and fails the paired
test, and a result that depends on which of two summaries you quote is not a result.

---

## ITERATION 2 — ADP-versus-projection gap (Task 1's rank 1, CIRCULAR): REVERTED

Mechanism: the market's disagreement with the projection. Reported because Task 1 ranked it
first, and **labelled circular throughout** -- ADP is partly derived from the same projections
the board is built from, so this measures the distance between the board and a market that has
already read the board.

    2019 -0.331   2020 +0.331   2021 -1.178   2022 +0.022
    2024 -1.322   2025 -0.266
    MEAN -0.457, also beats the noise floor

    paired over players: -0.212 [-0.667, +0.229]  n=733   NOT RESOLVED

Same shape as iteration 1, larger nominal effect, same verdict. **DISPOSITION: REVERTED**, and
it would have been reported as circular even had it resolved.

---

## what iterations 1 and 2 establish

**Task 1's ceiling predicted this and the iterations confirmed it.** A signal explaining 3-7% of
residual variance cannot move a rank metric detectably, and neither of the two best-ranked
signals did. The board is at its information limit.

The noise floor is also the right instrument in a way `audible#85`'s was not: under
leave-one-season-out a hash makes the board *worse*, so "beats the noise floor" is a genuine
bar here rather than an artefact of a short fitting window. Both signals cleared it on the
season-mean and neither cleared the paired test, which is the more reliable statistic -- 750
player-observations against six season summaries.

---

## ITERATION 3 — rookie draft capital (2e): REVERTED

Mechanism: rookies have no prior-season usage, so every usage signal is null for them by
construction. Draft capital is the only thing they carry. A first-round back and a sixth-rounder
get similar projections and different outcomes.

### G7 holds, and injection 4 fires

    2022: 94 players with no prior-season row, 397 with one

    rookies_only=True   veterans moved   0   rookies moved  68   G7 HOLDS
    rookies_only=False  veterans moved 303                       INJECTION 4 FIRES

The restriction is real rather than asserted: the identical term without it moves three hundred
veterans, so G7 is testing something that could fail.

### the result

    2019 -0.591   2020 +0.216   2021 -0.043   2022 -0.024
    2024 -0.416   2025 +0.286
    MEAN -0.095   (noise floor +0.364, so it beats the floor)

    paired over players, lambda +0.10:  +0.282 [-0.053, +0.643]  n=752  NOT RESOLVED

**The two summaries disagree in SIGN.** The season-mean says -0.095 (better); the paired
per-player test says +0.282 (worse). They disagree because one weights six seasons equally and
the other weights 752 players, and neither interval excludes zero.

**And the fitted weight is unstable**: five folds chose +0.10, one chose -0.05. A coefficient
that flips sign across folds is the same failure Task 1 used to discard `td_oe`, appearing here
in the fitted weight rather than in the diagnostic.

**DISPOSITION: REVERTED.**

---

## TASK 2 SUMMARY — three signals, three reversions, one consistent story

    signal                 season-mean   paired per-player          floor
    snap share (rank 2)         -0.539   -0.072 [-0.307,+0.162] ns  +0.364
    ADP gap (rank 1, circ.)     -0.457   -0.212 [-0.667,+0.229] ns  +0.364
    rookie draft capital        -0.095   +0.282 [-0.053,+0.643] ns  +0.364

All three beat the noise floor on the season-mean. **None resolves on the per-player test**,
which is the more reliable statistic -- roughly 750 player-observations against six season
summaries. Two of the three have a season-mean driven by a single season, and the third has a
fitted weight that flips sign across folds.

**This is exactly what Task 1's ceiling predicted.** A signal explaining 3-7% of residual
variance out of sample cannot move a rank metric detectably, and none of the three best-ranked
signals did.

`td_oe`, the handoff's 2a and its "strongest prior", was not tested at all: Task 1 put it
twelfth of thirteen with a sign that flips half the time. Testing it would have cost a run to
confirm what the diagnostic already showed, and the diagnostic is the cheaper instrument -- that
is the point of doing Task 1 first.

---

## G5 — THE 2026 PREDICTION, committed here before the season is played

The only genuinely clean test left. 2024-2025 has been read by `audible#84` and `audible#85`, so
nothing reported above is confirmatory. This is scored once, in January 2027, on green_hope
under symmetric indexing.

**PREDICTION: prior-season snap share at lambda = +0.05 changes 2026 RWRE by 0.0 +/- 0.5 RWRE,
and the change will not be resolvable on a paired per-player test.**

Direction: slightly negative (a small improvement) is more likely than positive, because five of
six folds preferred a positive weight and four of six seasons improved. Size: bounded by Task
1's ceiling -- 3-7% of residual variance cannot produce more than a few tenths of an RWRE.

**What would falsify it:** an improvement larger than 0.5 RWRE, or any resolved paired interval
in either direction. Either would mean the ceiling measured in Task 1 is wrong, which is the
single most useful thing a 2026 score could tell the next session.

Secondary, same terms: the ADP-gap signal changes 2026 RWRE by 0.0 +/- 0.7, and remains
uninterpretable because it is circular.

---

## ADVERSARIAL REVIEW — THE CEILING CLAIM IS OVERTURNED

One foreground agent. It overturned the session's headline, and I verified the kill shot myself
before accepting it. **Everything in the Task 1 section above that reads as an information
claim is withdrawn.** What survives is listed at the end.

### the kill shot: the residual is anti-correlated with the projection BY ALGEBRA

`residual = realised_rank - projected_rank` forces

    corr(residual, projected_rank) = -sqrt((1 - rho) / 2)

where rho is corr(realised, projected). Verified directly, twelve of twelve position-seasons
matching to three decimals:

    2021 QB rho 0.770  predicted -0.339  observed -0.339
    2021 RB rho 0.768  predicted -0.341  observed -0.341
    2022 TE rho 0.653  predicted -0.417  observed -0.417
    2024 RB rho 0.822  predicted -0.298  observed -0.298
    ... 12/12 MATCH

**The residual carries a -0.30 to -0.42 correlation with projected rank that is pure algebra
and zero football.** Any predictor that correlates with projected rank inherits a correlation
with the residual for free. And every one of my "sign-stable" predictors correlates hard with
projected rank -- snap share at -0.56 to -0.80.

### so the "sign-stable 5" filter was recording its own definition

Partial correlations, projected rank held constant. **All eight flip sign:**

    predictor           pos   r(x,res)   partial   flip
    prior_snap_share    RB      +0.209    -0.086   FLIPS
    prior_snap_share    WR      +0.246    -0.061   FLIPS
    prior_tgt_share     RB      +0.202    -0.027   FLIPS
    prior_tgt_share     WR      +0.257    -0.088   FLIPS
    prior_ay_share      WR      +0.269    -0.026   FLIPS
    draft_round         WR      -0.163    +0.020   FLIPS

The section above calls sign stability "the filter that matters". It was a filter on how hard a
predictor tracks the board's own ordering.

### and the board's own projected rank dominates every signal

    position   projected-rank percentile ALONE   prior_snap_share alone
    QB                              13.13%                       0.52%
    RB                              10.50%                       4.36%
    WR                              12.17%                       6.03%
    TE                              14.81%                       3.71%

**The single best "predictor" of the residual is the board restating itself**, at 10.5-14.8%,
which is regression toward the mean and is not new information by any reading. Stripping that
channel, the reviewer measured `prior_snap_share`'s incremental contribution at **-0.25% to
+2.12%**, with its largest component -- WR's headline 7.24% -- going to approximately zero.

**"The ceiling is 3-7% for one honest predictor" is WITHDRAWN.** The honest number is
essentially zero once the mechanical channel is removed.

### the negative R2 was estimator variance, not a finding

A permutation null -- the real design matrix with its real collinearity, y shuffled within
(position, season) so it is noise by construction, identical recipe, 500 draws:

    position   n_fit   REAL walk-forward   null median   percentile of real
    QB            47            -154.97%      -127.52%              40th
    RB            76             -36.83%       -19.85%              11th
    TE            44            -103.77%       -64.52%              25th
    WR            92              +1.58%       -17.03%              98th

**Pure noise reproduces those numbers.** QB's -154.97% sits at the 40th percentile of the noise
distribution and RB is worse than typical noise. Only WR is distinguishable.

I wrote that thirteen parameters "memorises rather than describes", which is right, and then
converted it into "the board is at its INFORMATION limit", which does not follow. It is a
statement about estimator variance at n_fit=47 with 14 parameters. **That inference is
withdrawn.**

Two further contributors the review isolated: 100 of QB's 155 percentage points come from ONE
near-duplicate column (`sd_rel` and `spread_rel` correlate at r=0.995, VIF 160) -- dropping it
alone moves QB from -154.97% to -54.53%. And the y-standardisation I chose inflates the number
by 33 points at QB and 52 at TE against the stricter variant.

### three things that need restating rather than withdrawing

**The fit window is misstated.** "Fit 2019-2022" is really 2021-2022: in WR 2019 four predictors
are 100% missing and in 2020 `career_outlier` is, so complete-case filtering drops those seasons
entirely. Actual n_fit is **47 (QB) and 44 (TE) against 14 parameters** -- 3.4:1 and 3.1:1, not
the "roughly a hundred complete cases" the section above claims (that is the early+late total).

**The in-sample column is a different model from the walk-forward column.** The 20.37 / 9.49 /
16.01 / 21.94 figures are an all-seasons pooled fit; the actual 2021-22 in-sample values are
47.53 / 25.65 / 20.27 / 23.03. Presenting them side by side implied one fit where there were
two.

**`prior_snap_share`'s join is lossy and biased toward the players it needed to be unbiased
about.** Only 4,099 of 5,084 `pfr_player_id` values (80.6%) reach gsis, and coverage falls
monotonically with projected rank -- RB Q1 88.6% down to Q4 65.1%. The excluded players sit at
the low-projected tail, which is exactly the arm where the mechanical residual-projection
relation is strongest.

### what SURVIVES the review

**`sim/residual.py::ols` is arithmetically exact.** Checked against a noiseless known answer
(max error 8.9e-16) and against an independently written modified-Gram-Schmidt QR on noisy data
(max beta difference 4.4e-16, identical R2). The 1e-12 pivot guard never fired on real data. The
regression was never the problem.

**`td_oe` is still refuted, and this is the session's durable finding.** The handoff's "strongest
prior" ranks last or next-to-last under every pooling the reviewer tried, raw and
projection-stripped alike (0.08% to 0.10%). That refutation does not depend on the broken
channel.

**Task 2's three iterations are untouched.** They score RWRE through `sim/rank.py` and never
call `residual.ols`. All three were reverted on their own evidence, and the G6 ordering gate and
the +0.364 noise floor are independent of everything above.

**The four data-availability refutations stand**, as does the finding that FFA's projections file
is a top-N export.

### the honest summary, replacing the one above

A rank-difference residual cannot measure "what the board is missing", because it is
anti-correlated with the board by construction. **The correct diagnostic controls for the
projection first** -- partial correlation, or regressing the residual on projected rank and
analysing what is left. Done that way the remaining signal is roughly zero to two percent, which
is a weaker and much less quotable claim than the one I published, and it is the one the data
supports.

The session's practical conclusion is unchanged and rests on Task 2 rather than Task 1: three
signals, three reversions, none resolving on a per-player test. **The board is unchanged.**
