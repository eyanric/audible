# S2b — search the space, don't check a list

`audible#84` built a validated harness and then ran four hand-written hypotheses. This session
fixes the metric's known blindness, then searches the space instead of checking a list.

Appended as each result lands.

---

## TASK 2.0 — the metric was blind to half the board, and now is not

`audible#84`'s own adversarial review measured the primary metric as **4.4x asymmetric**. The
weight was indexed by BOARD rank -- the pick you spend -- so the metric priced "do not draft a
bust early" and was nearly blind to "find a sleeper". A source or signal could differ
substantially at late-round value and that metric structurally could not see it.

### three indexings

    board       w = 1/round(board_rank)      audible#84's
    realised    w = 1/round(realised_rank)   the mirror
    symmetric   w = max(board_w, realised_w) prices both

`symmetric` takes the LARGER of the two: an error is costly if EITHER the pick was expensive OR
the player was valuable. It is the only one of the three that can see both failure modes.

### the asymmetry, measured under each (green_hope 2021)

    indexing    bury-the-best   promote-the-worst   asymmetry
    board                1.29                5.66       4.38x
    realised             5.66                1.29       0.23x
    symmetric            5.50                5.50       1.00x

`realised` is not a fix -- it is the same blindness pointed the other way, and it would have
made "roster a bust" nearly free. **`symmetric` is exactly balanced at 1.00x.**

### G1 holds under all three, in all three leagues

    league          board                realised             symmetric
    green_hope      0.000000 / 48.35     0.000000 / 48.40     0.000000 / 53.46
    danger_zone     0.000000 / 60.23     0.000000 / 60.27     0.000000 / 66.62
    boyfun          0.000000 / 72.25     0.000000 / 72.26     0.000000 / 79.78

(perfect board / shuffled mean). Symmetric's chance level is higher because `max` produces
larger weights; the perfect board is still exactly zero, which is what G1 asserts.

---

## G2 — every audible#84 headline, re-reported under the new indexings

### the source equivalence SURVIVES, and that is the important one

`ffa - espn`, paired over players, out-of-sample 2024-2025:

    league        board                    realised                 symmetric
    green_hope    +0.22 [-0.68,+1.12] ns   +0.58 [-0.57,+1.81] ns   +0.30 [-0.76,+1.42] ns
    danger_zone   -0.02 [-1.09,+0.97] ns   -0.24 [-1.76,+1.24] ns   -0.05 [-1.33,+1.20] ns
    boyfun        +0.32 [-0.58,+1.20] ns   +0.47 [-0.88,+1.82] ns   +0.48 [-0.68,+1.62] ns

**Not resolved under any indexing, in any league.** The bounded equivalence audible#84 reported
was not an artifact of the asymmetric weighting. No source "pulls ahead under realised-rank
weighting", which was the specific thing the handoff asked this task to look for.

### sleeper's boyfun win SURVIVES and GROWS

`espn - sleeper` in boyfun:

    board      +2.86 [+1.07, +4.62]  RESOLVED
    realised   +4.04 [+1.35, +6.69]  RESOLVED
    symmetric  +3.69 [+1.41, +5.94]  RESOLVED

Resolved under all three, and larger under the indexings that price sleepers. Sleeper's
advantage in boyfun is partly an advantage at players the old metric under-weighted.

### one thing the new indexing does change

Absolute levels move, and the NOMINAL green_hope leader flips:

    green_hope   board      ffa 20.27  espn 20.33  sleeper 21.52  ecr 30.27
                 realised   espn 19.34  ffa 19.96  sleeper 20.10  ecr 28.27
                 symmetric  espn 22.75  ffa 22.94  sleeper 23.71  ecr 32.18

Under `board` ffa is nominally first by 0.06; under `realised` and `symmetric` espn is
nominally first by 0.6 and 0.2. All of it is inside the interval, so nothing is resolved and no
claim changes -- but it is worth stating that the nominal ordering was never stable and reading
it as a ranking was always over-reading.

`ecr` remains resolvably worst under every indexing.

### danger_zone moves toward resolving but does not

`espn - sleeper` in danger_zone goes +1.42 ns (board), +2.54 [-0.19, +5.30] ns (realised),
+2.05 ns (symmetric). Under `realised` the interval nearly excludes zero. Recorded as a
near-miss rather than a result.

---

## PRE-REGISTRATION — the search

Committed before the search space was implemented and before any candidate was evaluated.

### the indexing the search optimises: `symmetric`

Fixed here and not changed again. It is the only one of the three with an asymmetry of 1.00x,
so it prices drafting a bust and missing a sleeper equally. Optimising `board` would inherit
the blindness this session exists to remove; optimising `realised` would inherit its mirror.

### the splits

    fit      2019, 2020, 2021   within-candidate estimation
    select   2022, 2023         THE SEARCH OPTIMISES HERE
    report   2024, 2025         touched ONCE, by ONE candidate

Candidates are ranked by their SELECT score. Their FIT score is reported alongside as a
stability check: a candidate that is good on select and bad on fit is fitting two seasons of
noise, and that is visible without spending the holdout.

**The cost, stated honestly.** Three seasons of fitting rather than four, two select seasons
rather than three, and exactly one look at the holdout. That is a real loss of power and it is
the price of the number at the end meaning what it says.

### an exception to the holdout, declared rather than discovered

**G2 required re-reporting `audible#84`'s headlines, and those headlines are computed on
2024-2025.** So the report split's BASELINE is already known: espn scores 22.75 there under
symmetric indexing in green_hope. That could not be avoided -- the gate demanded it, and the
numbers were already published by the prior session.

What that does NOT include is any candidate. The lock below forbids evaluating a SEARCH
CANDIDATE on the report seasons until one is fixed by hash. Knowing the incumbent's score is
not the same as tuning against the holdout, but it is not nothing either, and it is recorded
here rather than left for a reviewer to find.

### the lock (G3), mechanical

`sim/holdout.py` refuses to serve report-season data to the search unless
`sim/runs/s2b-candidate.lock` exists AND is tracked by git. The lock names one candidate and
carries its sha256. Reading the holdout before that file is committed raises rather than
returns.

### the space: eight knobs, each with a reason to exist

    1  w_espn        [0,1]        source blend weight, espn
    2  w_ffa         [0,1]        source blend weight, ffa
                                  (sleeper takes the remainder; the three are a simplex)
                                  REASON: audible#84 found the winner rotates by rulebook and
                                  the per-position bests differ. A blend can express that; a
                                  single source cannot.
    3  qb_depth      [1.0, 2.0]   multiplier on QB rostered count
                                  REASON: rostered_counts gives a 1-QB league's QB no bench at
                                  all, landing replacement at QB8 against a league that
                                  rosters ~13. 1.625 is that reality.
    4  flex_depth    [0.7, 1.3]   multiplier on RB/WR/TE rostered counts
                                  REASON: the bench split across flex-eligible positions is a
                                  rule of thumb, never measured.
    5  usage_lambda  [-0.15,0.30] prior-season target share, as in audible#84
                                  REASON: INCLUDED BECAUSE IT IS A KNOWN NULL. A search that
                                  cannot rediscover a measured zero is not searching honestly.
                                  This is G7.
    6  shrink        [0.0, 0.40]  shrink projected points toward the positional mean
                                  REASON: projections are noisy and shrinkage is the standard
                                  variance trade. Never tried here.
    7  vorp_mix      [0.0, 0.50]  blend the VORP ordering toward raw points
                                  REASON: VORP fully de-levels positions, raw points fully
                                  ignores scarcity. The truth may be between, and audible#84
                                  only ever ran the VORP end.
    8  noise_lambda  [-0.20,0.20] a pure-noise multiplier on projected points
                                  REASON: INJECTION 4. Its fitted weight must land near zero.
                                  A search that gives a random number a large weight is
                                  overfitting and its result is void.

Eight, which is the cap. Two of the eight (5 and 8) exist to be found near zero rather than to
help, so the effective search is over six.

### the blend, and a caveat it forces

Arms cover different seasons: espn has no 2023, sleeper has no 2019 or 2020. Rather than
shrink the window to the intersection -- which would leave one fit season and one select
season -- **the blend renormalises over whichever arms exist in that season**, and over
whichever arms carry that player.

The caveat this forces, stated now: **a blend weight does not mean the same thing in every
season.** In 2019-2020 it is a two-way espn/ffa mix; in 2023 a two-way ffa/sleeper mix; in
2021-2022 and 2024-2025 a three-way mix. A weight fitted mostly on two-way seasons may not
transfer. That is a real limitation of blending across corpora with different coverage and it
cannot be engineered away without discarding half the data.

### the search

Random search over the eight-dimensional box, with the three blend weights drawn from a
Dirichlet so the simplex is sampled uniformly rather than through its corners. **Not a grid** --
a grid over eight knobs either explodes or samples the corners worst.

The number of candidates and the wall-clock are reported. So is the WHOLE DISTRIBUTION: median,
p5, p95, and the winner's margin over the median. If a thousand candidates all land within half
an RWRE of each other, the space is flat and the board is already near a local optimum -- and
that is the finding, not the winner.

### the null, pre-registered

The identical search is re-run with the FIT-SEASON LABELS SHUFFLED -- realised outcomes permuted
among players, so any structure is destroyed. Whatever improvement that search finds is the
floor available from searching alone. **A real result must beat its own shuffled null**, and the
two are reported side by side.

### the disposition rule, fixed in advance

SHIP only if the single committed candidate beats the incumbent on the report split, under the
pre-registered symmetric indexing, by more than its shuffled-label null found on select.
Otherwise DO NOT SHIP, whatever the select-split number said.

---

## THE SEARCH — 4,000 candidates, and the null is the result

Random search over the eight-knob box, ranked on the select split (2022-2023), symmetric
indexing. 33.1 seconds of wall-clock. The report split was not touched: `sim/holdout.py` raises
until a candidate is committed by hash, and it was verified to raise.

    incumbent (espn alone, default transform)
      fit    22.109
      select 22.892

### the distribution, which is the finding rather than the winner

    real search      n=4000
      best      22.540
      p5        26.138
      median    32.060
      p95       45.558
      worst     54.053
      winner's margin over median: 9.520

**The space is not flat -- and it is the incumbent that is near the top of it.** The median
random candidate scores 32.06 against the incumbent's 22.89. Fewer than 5% of 4,000 draws even
reach 26.1. The current board is better than roughly everything the space contains, and the very
best draw improves on it by 0.352 RWRE.

### the shuffled-label null, and it settles the session

The identical search, re-run with realised values permuted among players so that all structure
is destroyed:

    shuffled-label null   n=4000
      best      46.699
      median    53.378
      incumbent on shuffled labels: 55.404

    REAL search gain over incumbent:  +0.352
    NULL search gain over incumbent:  +8.705
    real beats its own null by:       -8.353

**Four thousand draws over eight knobs can extract 8.705 RWRE from pure noise. Against real
data the same search extracts 0.352.** The measured gain is a twenty-fifth of the floor
available from searching alone.

This is the number the pre-registration existed to produce. Without it, +0.352 reads as a
small improvement and a session could report it as one. With it, +0.352 is indistinguishable
from -- and far below -- what searching would find in a table of random numbers.

**DISPOSITION: DO NOT SHIP**, by the rule fixed in advance.

### G7 — the search rediscovers both known nulls

Two of the eight knobs exist to be found near zero. Top-50 candidates by select score:

    usage_lambda   mean +0.0275  median +0.0320   sampled range -0.150..+0.300
    noise_lambda   mean -0.0032  median -0.0171   sampled range -0.200..+0.200

`usage_lambda` lands near zero and well below the centre of its sampled range (+0.075),
matching `audible#84`'s measured null. `noise_lambda` -- a pure hash of player and season, with
no information in it by construction -- lands at essentially zero. **The search did not assign
a random number a large weight, so its result is not void on G7's terms.** It simply has
nothing to find.

### what the top-50 preferred, reported without over-reading

    w_espn      mean 0.196   median 0.170
    w_ffa       mean 0.249   median 0.194
    w_sleeper   mean 0.555   median 0.594
    qb_depth    mean 1.341   median 1.289
    flex_depth  mean 1.029   median 1.048
    shrink      mean 0.172   median 0.150
    vorp_mix    mean 0.053   median 0.044

The top-50 of 4,000 is a selected set and these are not fitted values. Two are worth noting and
neither is a claim: the blend leans sleeper-heavy even in green_hope, where `audible#84` found
sleeper nominally WORST as a single source; and `qb_depth` leans above 1.0, in the direction
`audible#84`'s hand-written iteration 4 could not resolve. Both are consistent with noise at
this margin, and the null says the whole top of the distribution is.

### the winner, and its own instability

    select 22.540   fit 22.156   (incumbent fit 22.109)

    w_espn 0.327  w_ffa 0.066  w_sleeper 0.607
    qb_depth 1.077  flex_depth 0.779  shrink 0.292
    vorp_mix 0.016  usage_lambda -0.025  noise_lambda -0.046

**The best candidate on select is WORSE than the incumbent on fit** -- 22.156 against 22.109.
It is a select-only candidate, which the fit-split stability check flagged without spending the
holdout, exactly as the pre-registration intended it to.

The top ten make the same point. Several candidates ranked below the winner on select are
better than it on fit (21.181, 21.692, 21.947, 21.985), and one is dramatically worse (25.251).
Select rank and fit rank are close to unrelated across the top of the distribution, which is
what a flat, noise-dominated optimum looks like.

The winner is carried to the holdout unchanged, because the selection rule was fixed in advance
and swapping to a more stable candidate after seeing the fit scores is precisely the error the
whole apparatus exists to prevent.
