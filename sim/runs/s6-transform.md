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

## PHASE 3 — four shapes. The first run was wrong; the corrected run has three of them ahead.

**The first version of this phase reported that all four shapes lose, and that was an artifact
of my own design matrix.** The phase 3–6 review found it and it is the most important correction
in the session.

`design` z-scored the `projection` column **within position**, which destroys the level. The
incumbent orders by `points − replacement(pos)`, which in z-space is a per-position **affine**
map — a slope *and* an intercept. The design supplied per-position intercepts (the dummies) and
a single **global** slope, so it structurally could not represent the board it was being asked
to beat. Handed only the projection column and fitted **in-sample**, ridge scored **33.59
against the incumbent's 18.40** in 2019.

The fix is three columns, `pos × projection`. No outcome, both factors known preseason — a
specification fix, not a new input. The booster was separately underfit: 60 rounds × 0.05
shrinkage is a total learning budget of 3.0, and it had no fitted hyperparameter at all.

    shape          before    after   vs incumbent   eff params   what it does
    incumbent               22.425                         1.0   points -> replacement -> VORP
    boosted        24.574   22.114        -0.312          24.0   600 stumps x 0.02
    two-stage      25.083   22.382        -0.044          39.3   predict points, then incumbent
    learned        24.277   22.418        -0.008          38.2   predict VORP from all inputs
    quantile       22.656   22.656        +0.231           1.0   rank on points + q*sd_pts

`quantile` is unchanged because it never touched the design matrix.

    per season   2019    2020    2021    2022    2024    2025
    incumbent   18.40   23.41   24.40   22.89   25.57   19.89
    boosted     17.76   23.74   22.78   22.65   25.24   20.51
    two-stage   17.47   24.62   21.46   22.93   25.46   22.36
    learned     17.78   24.54   21.77   25.00   25.31   20.11
    quantile    18.78   23.73   24.53   23.20   25.54   20.16

**These are small margins — the best is under a third of a rank slot** — and phase 6 carries
them to the other two leagues, which is where they are decided.

### the per-position table, and a mirror image

    shape        QB     RB     TE     WR
    incumbent   4.53   8.33   5.56  10.73
    boosted     5.07   8.50   5.33  11.02
    two-stage   4.81   8.19   5.68  10.58
    learned     4.60   8.32   5.62  10.88
    quantile    4.94   8.15   5.46  10.49

**The boosted shape is WORSE at quarterback, running back and wide receiver, better only at
tight end — and better board-wide by 0.312.** Its entire gain is in the cross-position
interleave. `quantile` is the exact mirror: better at RB, TE and WR, worse at QB, and worse
board-wide.

So the two shapes that move the needle move it through opposite channels, and neither improves
both. The interleave and the within-position orderings are close to a zero-sum trade in this
harness, which is the `shrink`/FLEX-allocation mechanism phase 2 measured showing up as a
design constraint rather than a curiosity.

### the boosted model still spends most of itself on the incumbent's own structure

    pos_QB                  32.9%      ffa_dropoff__present     6.0%
    projection              23.2%      pos_RB                   4.1%
    pos_QB_x_projection     15.3%      contract                 2.7%
    pos_RB_x_projection      8.4%      ffa_dropoff              2.0%
                                       uncertainty              1.9%
                                       ff_opp_exp               1.1%

**About 84% of the model is the projection and the position structure** — that is, the model
re-deriving what the incumbent gets for free by subtracting a per-position replacement level.
The twenty football inputs together account for roughly a tenth of it, and the largest single
one is `contract` at 2.7%.

**And a missingness indicator is still ahead of every football value at 6.0%.**
`ffa_dropoff__present` means "this player was in FFA's top-N export at all", which is FFA's
editorial judgement leaking in as a quality proxy. Vintage, so not an outcome leak, but any
future model must either drop the indicators or report how much of its skill is fame.

### INJECTION 2 — the information-free input

    noise importance, every fold:  0.0000%  at 60 rounds
                                   0.156%   at 600 rounds
    boosted RWRE with the sha256 and without it: identical to three decimals

The first run reported "zero, exactly, in all six folds" and the review pointed out that this
was an **underfitting artifact** — at 60 rounds the model touched only 7.5 of 46 columns and
never had enough splits to consider the sha256 at all. At 600 rounds it touches 24.8 columns and
the hash acquires 0.156%. It still clears the 2% gate comfortably, and now it clears it having
actually been offered the chance to use it.

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

## PHASE 6 — the honest verdict: 0 of 9, and the cross-league test is what settles it

Three shapes carried to all three leagues. Running only `quantile` was a defect the review
caught: a verdict of "does not beat in any league" that never ran the shape which ties in
green_hope is not a verdict.

    league             shape       incumbent   rebuilt    delta   sign p   verdict
    espn_green_hope    quantile        22.43     22.66    +0.23    0.062   DOES NOT BEAT
    espn_green_hope    learned         22.43     22.42    -0.01    0.969   DOES NOT BEAT
    espn_green_hope    boosted         22.43     22.11    -0.31    0.438   DOES NOT BEAT
    espn_danger_zone   quantile        28.10     28.56    +0.46    0.500   DOES NOT BEAT
    espn_danger_zone   learned         28.10     28.92    +0.82    0.312   DOES NOT BEAT
    espn_danger_zone   boosted         28.10     30.05    +1.94    0.031   RESOLVABLY WORSE
    sleeper_boyfun     quantile        32.63     32.58    -0.05    0.688   DOES NOT BEAT
    sleeper_boyfun     learned         32.63     33.35    +0.72    0.250   DOES NOT BEAT
    sleeper_boyfun     boosted         32.63     35.06    +2.43    0.031   RESOLVABLY WORSE

    BEATS THE INCUMBENT: no, 0 of 9 league-shape pairs

The p is an **exact sign test** over the per-season deltas, with zero-deltas dropped as
uninformative. Its floor on six seasons is 2/64 = 0.031, so 0.031 is the strongest statement
available here and 0.000 — which the first version of this phase printed for danger_zone — is
unattainable.

### THE CROSS-LEAGUE TEST IS THE RESULT

**`boosted` is −0.31 in green_hope and +1.94 and +2.43 in the other two, both resolvably
worse.** The one shape that looked like a gain is the one that fails hardest elsewhere, and it
fails in the direction that says overfitting: it was selected on green_hope's six seasons and
it does not survive contact with a league that scores differently.

Green_hope's −0.31 is itself **not resolved** (p 0.438). So the honest reading of phase 3's
corrected table is not "three shapes beat the incumbent" but **"three shapes are
indistinguishable from the incumbent on the league they were built on, and two of them are
resolvably worse on the leagues they were not."**

`quantile` is the only shape that never loses badly anywhere — +0.23, +0.46, −0.05 — which is
what a one-parameter model buys: it cannot overfit enough to fail spectacularly, and it cannot
fit enough to win.

### per position, all three leagues

    green_hope    QB          RB          TE          WR
      quantile   +0.41       -0.18       -0.09       -0.24
      learned    +0.07       -0.01       +0.06       +0.15
      boosted    +0.54       +0.17       -0.23       +0.29
    danger_zone
      quantile   +0.14       -0.00       -0.02       -0.03
      learned    +0.09       -0.24       +0.12       +0.94
      boosted    +0.19       -0.47       -0.25       +1.64
    boyfun
      quantile   +0.07       +0.28       -0.09       -0.04
      learned    -0.10       -0.00       +0.39       -0.06
      boosted    +0.18       -0.25       +0.37       +0.43

**`boosted` is better at running back in two of three leagues and worse at wide receiver in all
three** — and wide receiver is the largest block in every pool, so that is where its board-wide
losses come from. The green_hope gain came through the interleave; in the other two leagues the
interleave gain is smaller than the WR damage.

### what this says about the standing goal

The goal was to rework the transform to take in all available information rather than staying
with `points → subtract replacement → sort by VORP`, which was described as "chosen at the start
and not a given".

**On this evidence the shape is close to load-bearing.** Four alternatives, one of them a
gradient-boosted model with 24 effective parameters over twenty football inputs, and the best
outcome anywhere is a statistical tie on the league it was fitted to. The incumbent's
per-position replacement subtraction is not an arbitrary choice that survived by inertia; it is
doing work that a model has to spend most of its capacity re-deriving — 84% of the boosted
model's importance is the projection and the position structure.

That is not proof the shape is optimal. It is evidence that the *information* is the binding
constraint rather than the *shape*: with six seasons, 39–43% coverage on every FFA-derived
input, and a floor whose own sd is comparable to every effect measured, no shape had room to
win.
