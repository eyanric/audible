# S6 — rebuild the transform

`audible#88` calibrated the referee, so for the first time an accept/reject decision means what
it says. This session fixes the two defects that corrupt everything downstream, inventories every
input the board already carries and discards, and tries transform shapes that are not
`points -> subtract replacement -> sort by VORP`.

Scripts and their committed output live beside this file as `s6_*.py` / `s6-*.out`.

---

## PHASE 1 — the two defects that corrupt everything downstream

### G1 — `score_board.per_position` scored each position over a slice of the GLOBAL pool

`members = [p for p in pool if position.get(p) == pos]`, where `pool = board[:pool_size]`. So
which players a position contributed depended on the **cross-position interleave**, and a term
that provably could not reorder anyone inside a position still moved its per-position score.

The fix takes each position's own top-N **from the full board**, with N derived from the league
config and nothing else — any rule that reads the board under test reintroduces the defect:

    espn_green_hope   pool 128   QB 18  RB 43  WR 43  TE 24
    espn_danger_zone  pool 160   QB 23  RB 53  WR 53  TE 30
    sleeper_boyfun    pool 190   QB 26  RB 55  WR 76  TE 33

Each starting slot contributes `num_teams` of demand, split evenly across the scoreable
positions eligible for it, so a FLEX adds a third each to RB, WR and TE.

**`availability` reading +0.000000 is a CONSISTENCY CHECK, NOT EVIDENCE.** The review caught
this and it is worth stating plainly: under the new rule the per-position member list is the
position's own top-N, and `availability` scales each position by a single positive scalar, which
is order-preserving. So the member list is byte-identical before and after and the metric
compares `x` with `x`. It is true by construction — `sim/signals.py::position_availability` says
so in its own docstring — and the half/config/double sweep is the same identity evaluated three
times.

    audible#87, global-pool slice   RB +0.159  QB -0.036  WR -0.028  TE +0.0004
    S6, position-local pool         exactly +0.000000 at all four, in all five seasons

(Five, not six: `availability` is built from seasons strictly before season−1 and
`player_stats_2018` is not pinned, so 2019 has no value at all. The old figures were also
concentrated rather than uniform — RB was non-zero in three of the five seasons and QB and WR in
one each.)

**The real evidence is a leakage test.** A per-player pseudo-random term applied to **RB only**:
under `scope=position` the QB, WR and TE cells hold no values at all, so those three positions
are untouched by construction and *must* read exactly zero. RB must move. This is falsifiable,
and the old rule fails it:

    season   NEW rule                                OLD rule
    2019     QB/WR/TE +0.000000  RB +0.893           TE -1.236, WR -0.071
    2020     QB/WR/TE +0.000000  RB +2.926           WR -1.056, QB -0.178, TE +0.392
    2021     QB/WR/TE +0.000000  RB +1.409           no leak
    2022     QB/WR/TE +0.000000  RB +3.432           WR -0.541, TE +0.044
    2024     QB/WR/TE +0.000000  RB +2.459           no leak
    2025     QB/WR/TE +0.000000  RB +4.325           TE -0.024

    worst leak into an untouched position:  NEW 0.00e+00   OLD 1.236
    seasons where the old rule leaked: 4 of 6

**An RB-only term moved tight end by 1.236 RWRE** — larger than any signal effect this project
has measured. That is what the fix removes.

**N is a pre-registered free parameter, and it is not innocuous.** `position_pool_sizes` gives
green_hope QB 18, but a 1-QB 8-team league only ever drafts about ten quarterbacks — QB#18 sits
at global board rank 158–262 against a 128-pick draft, so **half the QB metric is players nobody
drafts**. For an inert term N genuinely does not matter; for a term that carries information it
can decide the sign. Measured on `ngs_time_to_throw` at QB:

    2019  N=9 +0.811   N=18 -0.643   N=36 -2.032
    2021  N=9 -0.340   N=18 +1.790   N=36 +0.389
    2022  N=9 -1.477   N=18 -0.587   N=36 -0.294
    2025  N=9 +0.000   N=18 -1.063   N=36 +0.419

Sign flips in three of six seasons. **Every per-position conclusion in this session is therefore
reported across N**, and one that does not survive the sweep is not reported as a result.

**`position_pool` is required, not defaulted.** A fallback would have been a *third* rule —
neither the global slice nor the config-derived N — reachable by any caller that forgot the
argument. `score_board` now raises instead, and the three historical scripts that called it
without one were updated.

**This moves every per-position number in `audible#84` through `#87`.** The floor distribution
is redrawn under the fixed metric before anything in this session is adjudicated, because the
S5 floor's per-position draws were computed under the broken one.

### G2 — `search.py` and `signals.py` built different boards

`_season_inputs` resolved position with `position.update(loaded.position)` in arm order
espn -> ffa -> sleeper, so **the last arm won** and sleeper could overwrite espn. Measured
against espn, which is what `signals.py` reads:

    2019  arms [espn, ffa]            1 disagreement    2022  arms [espn, ffa, sleeper]  3
    2020  arms [espn, ffa]            1                 2024  arms [espn, ffa, sleeper]  3
    2021  arms [espn, ffa, sleeper]   7                 2025  arms [espn, ffa, sleeper]  1
    total 16 across six seasons

    00-0033338  espn RB -> resolved TE      00-0036825  espn QB -> resolved TE
    00-0037304  espn TE -> resolved RB      00-0037745  espn WR -> resolved RB

`setdefault` in the same arm order makes espn authoritative wherever it has the player, and the
other arms fill only what espn has never heard of. After the fix, **0 disagreements and the two
modules build byte-identical boards in all six seasons — asserted in the script.**

**espn-first is *a* resolution, not provably *the* one.** The justification "match what
`signals.py` reads" is circular; it makes search agree with signals by declaring signals correct.
There is a real architectural inconsistency underneath: **the realised side already buckets by
nflverse** — `realised_per_game` takes position from `player_stats_*.parquet` — so replacement
levels are computed in nflverse's buckets while the board is built in espn's. Measured: 20
espn-vs-nflverse disagreements across the six scored boards, and **0 inside the per-position
member lists**. So it has no measurable effect today and is recorded as a known inconsistency
rather than fixed here.

### `MIN_SD_REL` retired as the deciding rule

`audible#88` measured that of 217 cells the 20 its tuned threshold skipped **all held exactly
one distinct value**. A wider census over 389 cells confirms it: 20 skipped by both rules, **zero
cells where the threshold still decides, and zero where `distinct` is stricter**. The nearest
live cell sits 672,000x above the threshold.

**This change is behaviourally a no-op and should be described as one** — the code tests
`distinct <= 1` first and *then* still tests the floor, so the rule is the union and the skip set
is provably unchanged. What it buys is that the deciding condition is now a fact about the data
rather than a constant someone chose.


### Injections

    INJECTION 1  perfect board 0.000000 in all six seasons, and 0.000000 at every position
                 shuffled 42.137 to 57.802
    INJECTION 3  availability through the within-position path FAILS G5 on all four conditions
    INJECTION 4  shrink FAILS G5: moves a within-position ordering in 0/6 seasons


---

## THE FLOOR, redrawn under the fixed metric at K=80

`audible#88`'s floor was drawn with the broken per-position rule, so every per-position draw in
it was computed under a metric that no longer exists. K also moved from 40 to 80: a two-sided
reference-set test against K draws cannot report a p below `2/(K+1)`, so K=40 floored at 0.0488
and `audible#88`'s two resolutions sat exactly on that floor. K=80 floors at **0.0247**.

    locus   mean      sd     2.5%      97.5%     min      max
    board  +0.230   0.291   -0.448   +0.753   -0.828   +0.986
    QB     +0.233   0.267   -0.402   +0.710   -0.521   +0.804
    RB     +0.097   0.175   -0.284   +0.506   -0.524   +0.559
    WR     +0.254   0.379   -0.481   +0.859   -0.819   +0.863
    TE     +0.124   0.267   -0.398   +0.545   -0.508   +0.960

**The metric fix moved the floor itself, and most at wide receiver:**

    locus   audible#88 (broken, K=40)   S6 (fixed, K=80)
    board   +0.326 sd 0.378             +0.230 sd 0.291
    QB      +0.219 sd 0.191             +0.233 sd 0.267
    RB      +0.104 sd 0.136             +0.097 sd 0.175
    WR      +0.050 sd 0.497             +0.254 sd 0.379
    TE      +0.196 sd 0.424             +0.124 sd 0.267

**That WR move is NOT established, and the review's decomposition is why.** Splitting the 80
S6 draws into two independent K=40 halves *under the identical fixed metric*:

    locus   s5 K=40 broken   s6 first 40   s6 last 40   s6 K=80   MC se (K=80)
    board           +0.326        +0.268       +0.193    +0.230          0.033
    QB              +0.219        +0.252       +0.213    +0.233          0.030
    RB              +0.104        +0.102       +0.093    +0.097          0.020
    WR              +0.050        +0.344       +0.165    +0.254          0.042
    TE              +0.196        +0.056       +0.192    +0.124          0.030

The WR move of +0.204 is **2.29 SE**, and two halves of the same fixed-metric draws differ by
**0.180** — nearly the whole claimed effect. Across five loci one 2.3-SE reading is what noise
produces. TE is worse: its "fall" from +0.196 to +0.124 reverses entirely on the other half.
**So the honest statement is that the metric fix moved the floor by an amount K=80 cannot
resolve**, and phase 4 decides `ngs_separation` against a WR floor carrying a standard error of
about 0.042 on the mean and far more on the tails.

**The published 2.5%/97.5% endpoints are over-precise.** Bootstrapped over the draws, the 2.5%
endpoint has a standard error of 0.07–0.30; the board's −0.448 has a 95% interval of
[−0.828, 0.000] and is effectively unidentified. They are quoted to three decimals above because
that is what the script printed; they should be read as one significant figure.

**And the calibration is 3 events, not 400 independent tests.** 3/400 = 0.75% pools 80 draws
seen at 5 loci, and `board` is an aggregate of the four positions from the same draw. Per locus
the exact 95% interval on 1/80 is [0.03%, 6.77%] and on 0/80 is [0%, 4.51%] — **the data cannot
distinguish 1.2% from 5%.** "Still conservative" is an over-read; the honest claim is that no
calibration failure was detected, at a resolution that could not detect a mild one.

**Referee calibration under the fixed metric**: 3 false resolutions in 400 tests whose null is
true, **0.75% at a nominal 5%**. Still conservative, so the bootstrap interval is reported and
the reference-set p decides.

---

## PHASE 2 — every input, and whether it can move an ordering

**26 candidates. 26 pass the rebuilt G5. 5 excluded before testing, with the reason.**

That all 26 pass is not a finding about their quality. **G5 asks only whether a term is
MEASURABLE** — does it apply in more than one season, with real spread, moving a within-position
ordering if it claims within-position information. It is a floor on auditability, not on value.
`noise` passes it too, and `noise` is a sha256.

### coverage against ESPN's scoreable pool

    input               mean   note
    noise               100%   information-free by construction
    contract             84%
    availability         83%   five seasons, not six -- 2019 has no prior data at all
    snap_share           81%
    depth_slot           80%   the pin stops at 2024, so 2026 has no prior season
    td_oe                79%
    draft_round          78%   rookies only, so the applied subset is far smaller
    ff_opp_exp           71%
    ff_opp_diff          71%
    target_share         67%   2019 is 0% -- prior-season target data begins in 2019
    ffa_* (all eight)    39-43%
    age, uncertainty     42-43%
    adp_gap              42%
    ngs_separation       24%   receivers only
    ngs_cushion          24%
    ngs_rush_eff          9%   backs only
    ngs_time_to_los       9%
    ngs_time_to_throw     7%   passers only

**Every FFA-derived input is capped at 39–43%** because FFA's projections file is a top-N export
— 72 RB / 72 WR / 37 QB / 36 TE in 2022 — against an ESPN pool of 454–496. That is nine separate
candidate inputs that can never speak for more than about two players in five, and it is a
property of the source rather than of the signal.

**The Next Gen inputs look catastrophic at 7–24% and are not.** They are charted for one
position each, so the denominator is the whole board while the numerator is one position. As a
share of *their own* position they are far higher; the low number is the cross-position
dilution `audible#87` measured at 17.5x, visible here as a coverage figure.

### a defect in this session's own harness, found and fixed

`ff_opportunity`'s `season` column is a **string** in the pin, so `pl.col("season") == season-1`
raised `ComputeError`. The coverage helper caught every exception and returned 0%, so a broken
input was reported as an input that covers nothing — indistinguishable from an absent one. Both
were fixed: the filter casts, and the helper no longer swallows. `ff_opp_exp` and `ff_opp_diff`
went from a reported 0% to a real 71%.

### excluded before testing

    injuries / practice participation
        HARD STOP. audible#71 measured RB 2.58 games missed against WR 3.29 at ADP <= 100 --
        the opposite of the folklore -- and a player-level injury term is forbidden.
    participation (route running)
        Play-level, no season column, no gsis key. Route participation is the known nflverse
        gap and is delivered post-season only.
    ftn_charting
        Pinned 2022-2025. As a PRIOR-season term that is seasons 2023-2026, and ESPN has no
        2023 board, so two usable seasons. Too few for a six-fold LOSO.
    officials
        Not player-keyed. Nothing to join to a board.
    ffa points_vor / floor_vor / ceiling_vor / rank / position_rank
        FFA's OWN replacement transform of its own projection. Feeding these to a ranking model
        tests FFA's transform rather than an input.


### the phase-2 review found four inputs whose DEFINITION was wrong

Not "did not help" — wrong. Phase 3 was consuming them, so they were fixed before it ran.

**`ffa_ceiling` and `ffa_floor` were incoherent.** Defined as `ceiling/points` and
`floor/points`, they are mechanically a monotone *inversion* of the projection: r = −0.59 and
+0.58 against ESPN points. A 296-point back reads `ceiling_rel` 1.12 and a fringe back reads
1.7+. Both carried sign +1, i.e. both were declared "more is better", which cannot be true of a
quantity and its opposite. **Dropped**, and replaced with `ffa_skew` = `(ceiling − points) /
(points − floor)` — how lopsided the distribution is rather than how wide, which as a ratio of
two spreads does not inherit the projection's level.

**Five of the 26 candidates were one axis.** Pairwise within-position correlations:

    uncertainty vs ffa_spread        r = -0.98    a term and its own negation, listed twice
    uncertainty vs ffa_uncertainty   r = -0.80    same construct, opposite declared polarity
    the whole dispersion group       |r| 0.75-0.98

**Dropped** `ffa_spread` and `ffa_uncertainty`; `uncertainty` (`sd_pts/points`) carries the axis.

**`ffa_tier` and `ffa_aav` are the projection restated**, at Spearman 0.99 and 0.91 against
FFA's own points within position. Phase 2's own exclusion list rejects `rank` and
`position_rank` as "FFA's OWN replacement transform of its own projection" — these two are the
same thing and were kept by oversight. **Dropped**, applying the session's rule to itself.

**`age` is NOT vintage, and three sessions have called it vintage.** The FFA file stamps it at
export: across nine season files, **1,395 of 1,397 year-over-year transitions have delta exactly
0.0** while `experience` correctly increments by 1. Against `ff_playerids.birthdate` the offset
is +7.50 in 2019, +5.85 in 2022, +0.95 in 2025 — the file describes ages as of the ~2026 pull.

It is not an outcome leak, and the offset is near-uniform within a season so the within-position
z-scored *ordering* is nearly unharmed. But the level is wrong by up to seven years, the
birthday-month split perturbs the ordering by a year, and **`sim/residual.py::PREDICTORS`
carried the comment "FFA preseason projection file, vintage"**. Renamed `age_at_export` and both
comments corrected. `experience` is genuinely vintage.

**`depth_slot` averaged defence and special teams.** The pin carries Offense, Defense and
Special Teams depth entries; the unfiltered mean made a WR3 who returns kicks read as a WR2.
**32% of covered board players got a different value**, largest movers by more than a full slot,
Spearman 0.95 between the two versions. Now filtered to Offense and REG.

Its docstring was also wrong twice: `pos_rank` **is** populated — in the 554k newer-format rows,
which carry a NULL season and are therefore invisible to a `season == N` filter — and the pin
does **not** stop at 2024. It holds 2025 and the 2026 offseason in that second schema, so a 2026
board is blocked by a schema mismatch rather than by absent data.

**`ff_opportunity`'s denominator rewarded missing half a season.** Both fields divided by games
the player *appeared* in, so "expected fantasy points per game" scored a six-game player as
though he had played a full year — the median player had 9 rows in 2024 and only 101 of 604 had
17. Split into `ff_opp_exp` (volume: per **team** game) and `ff_opp_eff` (efficiency: over
expectation, per appearance).

**After the corrections: 21 candidates, all 21 pass G5.** The earlier count of 26 was inflated
by five terms that were duplicates or disguised projections.

### two coverage claims restated

**"Every FFA-derived input is capped at 39–43%"** — the cap is real and the join is exonerated:
the name+position join loses 0–4 rows a season (≤1.8%) and the mfl→gsis crosswalk loses zero, so
the top-N export is the whole constraint. But the run's own table reads **46% in 2025**, so the
range is a mean-of-means and not a cap. And it is **eleven** FFA-derived candidates, not nine.

**"The Next Gen inputs read 7–24% only because they are charted for one position each"** — both
halves wrong. `ngs_separation` and `ngs_cushion` reach **28% of tight ends**, not one position.
And within its own charted position the dilution factor is **1.96x at WR, 4.0x at RB, 7.6x at
QB** — not the 17.5x `audible#87` measured for a different quantity. Within-position coverage:

    ngs_separation      WR 47%   TE 28%
    ngs_rush_eff        RB 36%
    ngs_time_to_throw   QB 53%

Under half of receivers are charted. The low board-wide figures are only partly dilution; the
rest is real absence.


---

## THE INCUMBENT BAR THE HANDOFF QUOTES IS MEASURED UNDER A SUPERSEDED INDEXING

G8 requires the incumbent bar beside every result. The handoff gives **20.33 green_hope / 25.32
danger_zone / 30.94 boyfun**. None of the three reproduces under this session's metric. Searching
the combinations finds them exactly:

    league             quoted   board idx   realised idx   symmetric idx
                                 24+25        24+25          24+25
    espn_green_hope     20.33     20.33         19.34          22.73
    espn_danger_zone    25.32     25.32         23.64          27.42
    sleeper_boyfun      30.94     30.94         30.06          34.50

**All three match `board` indexing on 2024+2025, to the digit.** But `board` was superseded:
`audible#85` pre-registered `symmetric` after measuring `board` as **4.4x asymmetric** — burying
the best player costs 1.29 while promoting the worst costs 5.66 — and every session since has
used it.

Comparing a symmetric-scored rebuild against a board-scored incumbent is a **units error**, the
class of defect S2's G1 caught when a VORP-ordered board scored against raw realised points gave
the *perfect* board 13.99 instead of 0.

**The correct bar, symmetric indexing, all six seasons:**

    espn_green_hope   22.43      espn_danger_zone  28.10      sleeper_boyfun  32.63

Every result below is against that.

---

## PHASE 3 — four shapes, and all four lose

    shape          RWRE    vs incumbent   eff params   what it does
    incumbent     22.425                         1.0   points -> replacement -> VORP
    quantile      22.656        +0.231           1.0   rank on points + q*sd_pts
    learned       24.277        +1.852          26.9   predict VORP from all inputs
    boosted       24.574        +2.149           6.0   depth-1 stumps on all inputs
    two-stage     25.083        +2.658          34.5   predict points, then the incumbent

Effective parameters are the exact trace `tr((X'X + lam I)^-1 X'X)`, not the column count. Every
penalty was fitted **inside** the fold on the remaining seasons — never once across all six.

    per season   2019    2020    2021    2022    2024    2025
    incumbent   18.40   23.41   24.40   22.89   25.57   19.89
    quantile    18.78   23.73   24.53   23.20   25.54   20.16
    learned     23.03   26.61   24.94   25.18   25.21   20.70
    boosted     21.40   25.36   24.29   25.24   26.02   25.14
    two-stage   23.30   26.39   25.70   24.68   26.20   24.22

**The fitted quantile is +0.5 in five of six folds and +0.25 in the sixth** — the board should
be read *above* its mean, consistently. It still loses.

### the per-position table says something the board-wide number hides

    shape        QB     RB     TE     WR
    incumbent   4.53   8.33   5.56  10.73
    quantile    4.94   8.15   5.46  10.49
    learned     4.98   8.62   5.77  10.53
    boosted     4.91   8.24   5.43  10.96
    two-stage   4.75   8.80   6.05  11.13

**The quantile shape BEATS the incumbent at running back, tight end and wide receiver** — −0.18,
−0.10, −0.24 — and loses at quarterback by +0.41. It improves three positions out of four and
still loses board-wide.

**So its entire loss is in the cross-position interleave**, which is the `shrink` mechanism this
session already measured: a transform that changes the *shape* of a position's distribution moves
the FLEX allocation, `compute_vorp` reassigns a starter slot, and both replacement ranks shift.
Reading the board above its mean widens each position's spread by a different amount, because
`sd_pts/points` differs by position — so the interleave moves, and it moves the wrong way.

That is the most useful thing phase 3 produced: **the incumbent's replacement subtraction is
doing real work that none of these shapes replaced**, and the one shape that improves the
within-position orderings gives it all back at the interleave.

### the boosted model spends 40% of its capacity relearning replacement

    pos_QB                  40.0%
    projection              35.1%
    ffa_dropoff__present    11.4%
    pos_RB                   3.7%
    ngs_rush_eff__present    3.5%
    uncertainty              2.9%
    adp_gap__present         2.2%
    contract                 1.2%

Three quarters of the model is "is he a quarterback" plus "what did ESPN project". The position
dummies are the model rediscovering, badly, what the incumbent gets for free by subtracting a
per-position replacement level. **Not one of the twenty football inputs clears 3%** except a
missingness indicator.

**And the third-ranked feature is a MISSINGNESS INDICATOR.** `ffa_dropoff__present` at 11.4%
means the model learned that *being in FFA's top-N export at all* predicts realised VORP. That is
true and it is not football: it is FFA's editorial decision about who is worth publishing,
leaking in as a quality proxy. It is not an outcome leak — the export is vintage — but any future
model must either drop the indicators or report that a large share of its skill is "this player
was famous enough to be exported".

### INJECTION 2 — the information-free input

    noise importance, every fold:        0.0000%
    boosted RWRE with the sha256:        24.574
    boosted RWRE without it:             24.574
    incumbent:                           22.425

**Zero, exactly, in all six folds, and the RWRE is unchanged to three decimals.** The model
correctly refuses an information-free input — which is the thing `audible#85`'s search could not
do, where a sha256 bought 42% of the apparent gain.


---

## PHASE 4 — `ngs_separation` does NOT hold. Four independent lines, all the same way.

It was the only calibrated resolution this project had produced: p = 0.049 at WR in
`audible#88`, fitted weight +0.05 in all six folds, the only term whose weight never flipped
sign. **It does not survive the phase-1 metric fix.** A wrong call here is expensive, so all
four tests are reported, including the one that is merely suggestive.

### 1. the verdict itself

    signal     -0.558 [-1.394, +0.322]
    floor      +0.254 [-0.699, +1.288]
    difference -0.812 [-1.845, +0.325]      bootstrap: not resolved
    reference-set p 0.074 over 80 draws     floor of the test 0.0247
    -> NOT RESOLVED

`audible#88` read p = 0.049 at K=40 under the broken per-position metric. Under the fixed metric
at K=80 it is **0.074**. The fitted weight is still +0.05 in all six folds, which remains the
most stable thing about it.

### 2. the effect exists at exactly one pool size

    N = 21 (half)     signal +0.349    per season +0.00 +0.71 +1.01 +0.00 +0.37 +0.00
    N = 43 (config)   signal -0.558    per season -1.82 +1.17 -1.14 -0.46 +0.47 -1.56
    N = 86 (double)   signal +0.000    per season +0.00 +0.00 +0.00 +0.00 +0.00 +0.00

**The sign flips.** At half the pool separation is a *harm*; at double it is declined outright —
the LOSO fit chooses lambda = 0 in every fold. Phase 1 established that N can decide the sign of
a term that carries information, and required every per-position conclusion to survive the
sweep. This one does not survive it at all.

That also explains why `audible#88` saw it: the broken metric's WR slice held 37–47 players,
which is close to the config N of 43 — the one place the effect is visible.

### 3. the player-persistence test — WITHDRAWN, it has no discriminating power

This was published as "the single most diagnostic result": per-player rank-error improvement
correlated across every pair of seasons gives **mean r = −0.058 over 12 pairs, positive in only
4 of 12**, and the argument was that a physical measurement carrying a durable property of a
receiver should not behave that way.

**The review ran the same test on an ORACLE — realised VORP itself, injected as the signal.** It
is a perfect signal by construction and it works (WR RWRE 12.600 → 8.137 in 2019):

    signal                  pairs   mean r   positive
    ngs_separation             12   -0.058     4/12     <== the published result
    snap_share                 12   +0.031     7/12
    noise (a sha256)           11   -0.146     2/11
    ORACLE realised VORP       12   -0.048     4/12     <== a PERFECT signal
    ORACLE at lambda 0.20      11   -0.004     5/11

**A perfect signal scores −0.048 and 4 of 12 — statistically identical to `ngs_separation`, and
below `snap_share`.** The test cannot tell a perfect signal from a hash, so it cannot tell
anything.

The reason is structural: `benefit = error_before − error_after` is dominated by how badly ESPN
misranked that particular player in that particular season, which is season-idiosyncratic
whatever the signal is. **Withdrawn.** The revert now rests on three lines, not four.

### 4. leave-two-seasons-out, over every pair rather than the convenient one

    all six seasons                     -0.558   p 0.074
    without 2020 and 2024               -1.246   p 0.025
    without 2021 and 2025               -0.160   p 0.346   <== the pair audible#88 dropped
    without 2019 and 2025               +0.008   p 0.420   <== the worst pair
    14 of 15 pairs leave it negative

The concentration is real but it is **not the pair `audible#88` identified**. Under the fixed
metric the largest single contributor is 2019 (−1.82), not 2021. **Which seasons carry the
effect changed when the metric was corrected**, which is itself evidence that what is being
measured is not stable.

### the one thing that looked like a mechanism

    correlation of the per-season delta with, over six seasons:
      charted count            r = -0.862      <== the only |r| above the noise threshold
      WR pool size             r = +0.434
      separation sd            r = -0.425
      realised WR VORP sd      r = +0.328

More charted receivers, more benefit. That is a plausible mechanism — more coverage, more
signal. It is also **six points with four correlations examined**, where |r| below about 0.81 is
indistinguishable from zero. It is recorded as a lead for a session with more seasons, not as a
finding.

### DISPOSITION: REVERTED, on three lines rather than four, and it is closer than it looked

p = 0.074 under the corrected metric; the fit declines the term entirely at the largest pool
size and produces an incoherent sign-flipping fit at the smallest; and the seasons that carry it
moved when the metric was fixed. The persistence test is withdrawn (above).

**Two honest caveats against my own call.** First, the reference-set test is two-sided by
pre-registration, and **both** of the two draws at or below the signal are on the *improving*
side — a one-sided p would be 3/81 = **0.037**, which resolves. The revert depends on the
two-sided convention, which was fixed in advance and is the right one, but it is a coin's width.

Second, the N=86 reading of "+0.000" is a **decline, not a sign flip**: the LOSO fit chooses
lambda = 0 in all six folds, so the delta is zero by construction. Presenting it in a
three-point series as evidence that the sign flips overstated it. (The WR pool is 174–183 every
season, so N=86 is genuinely scoring 86 receivers — it is not a truncation artifact.) At N=21
the fitted lambda is `{2019: 0.0, 2020: -0.05, 2021: +0.05, 2022: 0.0, 2024: -0.05, 2025: 0.0}`
— sign-flipping across folds, so "+0.349 means separation is a harm at half the pool" is three
different fits averaged rather than one coherent one.

**Only N=43 produces a coherent fit at all**, which is itself the finding: the term is
measurable at exactly one pool size.

**This project now has zero resolved signals.** `audible#88`'s two resolutions were
`ngs_separation` at WR and `ngs_time_to_throw` at QB, both at p = 0.049 against a K=40 floor
drawn under the broken metric. The first is reverted here. The second is re-decided in phase 5.


---

## PHASE 5 — 61 loci, 2 resolve, both are HARMS, and 2 is below chance

Every one of the twenty inputs adjudicated at its stated locus against the K=80 floor drawn
under the fixed metric.

    resolved at a calibrated 5%: 2 of 61 loci
      improvements: NONE
      harms:        contract@TE (+0.958, p 0.049)
                    ffa_experience@TE (+0.772, p 0.049)

**And two is fewer than chance.** 61 loci tested at a nominal 5% expects about **3.1** false
resolutions; 2 were observed. Neither survives a Bonferroni threshold of 0.0008, and neither
*could*: the reference test's floor at K=80 is 0.0247, so **to resolve anything against 61
comparisons this harness would need K ≥ 2439 draws.** At thirteen seconds a draw that is nine
hours — affordable, and pointless, because the effect sizes are not there.

**`audible#88`'s second resolution is also gone.** `ngs_time_to_throw` at QB read p = 0.049 as a
harm; under the corrected metric it is **+0.228 at p = 0.889** — the 52nd of 61 loci. Both of
that session's resolutions have now evaporated: one under the metric fix, one under both.

The top of the table, so the next session does not re-run it:

    contract@TE            +0.958   p 0.049   RESOLVED WORSE
    ffa_experience@TE      +0.772   p 0.049   RESOLVED WORSE
    ngs_separation@WR      -0.558   p 0.074   not resolved
    age_at_export@WR       -0.510   p 0.074   not resolved
    target_share@RB        -0.101   p 0.099   not resolved
    adp_gap@RB             -0.174   p 0.099   not resolved
    availability@board     +0.813   p 0.099   not resolved

### INJECTION 5 — what a single floor draw would have decided

    26 of 61 loci get a DIFFERENT disposition:  43%
    audible#88 measured 5 of 18 = 28% on a smaller set

**23** of the 26 are false **RESOLVED BEATS FLOOR** — the single-draw mechanism manufactures
improvements. **2** are false RESOLVED WORSE (`contract@RB`, `ff_opp_exp@RB`). **1** is the
reverse: `contract@TE` reads "not resolved" against one draw and resolves against the
distribution. **43% of dispositions in this session would have
been wrong under the mechanism `audible#86` and `#87` used.**

### INJECTION 6 — the dilution

**16 of 61 loci carry a board-wide sign opposite to their locus sign**, including every one of
`depth_slot`'s three positions (+0.24/+0.27/+0.24 at locus, −0.500 board-wide) and both
`ngs_separation` loci. A board-wide number is not a weak version of a positional one; it can be
the opposite of it.

### THE COMBINATION CANNOT BE FORMED

The handoff's inclusion rule is: an input joins if it beats the calibrated floor **alone**, or a
phase-3 model gives it **stable importance across all six folds**.

- **First criterion admits nothing.** Zero improvements resolve.
- **Second criterion admits nothing either.** Of the twenty football inputs, the largest share
  the boosted model gives to any *actual value* — as opposed to a position dummy, the
  projection, or a missingness indicator — is `uncertainty` at **2.9%**.

There is nothing to combine. Reported rather than skipped, because "we tried to combine and
found no survivors" and "we did not try" are different claims and only one of them is true.


---

## PHASE 6 — the honest verdict: it does not beat the incumbent, in any league

The best shape phase 3 produced (`quantile`) carried to all three leagues, scored under the
pre-registered `symmetric` indexing, penalty fitted inside each fold.

    league             incumbent   rebuilt    delta   sign-flip p   verdict
    espn_green_hope        22.43     22.66    +0.23         0.031   DOES NOT BEAT
    espn_danger_zone       28.10     28.56    +0.46         0.000   DOES NOT BEAT
    sleeper_boyfun         32.63     32.58    -0.05         0.688   DOES NOT BEAT

    BEATS THE INCUMBENT: no, 0 of 3 leagues

The p is an **exact sign-flip test** over the six per-season deltas — all 2^6 sign assignments
enumerated, no bootstrap and no floor of hashes, because the question here is "does this shape
beat that shape" rather than "does this input beat nothing".

**Two of the three are resolvably WORSE.** green_hope improves in 1 of 6 seasons (p 0.031),
danger_zone in **0 of 6** (p 0.000). boyfun is a genuine tie: −0.05 with 3 of 6 seasons
improved, p 0.688.

### the per-position table is the same story in all three leagues

    green_hope    QB +0.41    RB -0.18    TE -0.09    WR -0.24
    danger_zone   QB +0.14    RB -0.00    TE -0.02    WR -0.03
    boyfun        QB +0.07    RB +0.28    TE -0.09    WR -0.04

**The rebuilt shape is better at wide receiver and tight end in all three leagues, and worse at
quarterback in all three.** In green_hope it improves three positions of four and still loses
board-wide by +0.23.

That is the session's structural result, and it reproduces across leagues with different scoring
and different roster shapes: **reading the board above its mean improves the within-position
orderings and gives it all back at the cross-position interleave.** `sd_pts/points` differs by
position, so a quantile shift widens each position's spread by a different amount, the FLEX
allocation moves, `compute_vorp` reassigns a starter slot, and the replacement ranks shift. It is
the `shrink` mechanism this session measured in phase 2, arriving as a cost rather than a
curiosity.

**The incumbent's per-position replacement subtraction is doing real work that four different
shapes failed to replace.** That is worth saying plainly, because it is the opposite of what the
standing goal assumed — the `points -> subtract replacement -> sort by VORP` shape was described
as "chosen at the start and not a given", and on this evidence it is load-bearing.
