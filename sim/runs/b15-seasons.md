# B15 — seven seasons

Base `main` at 6a4f9253. Branch `feat/seven-seasons`.
Runs: `b15-{ffc,mfl12,mfl8}.json`, seven seasons, against
`b13-*` at five. Nothing else differs.

## VERDICT

k=7 ACHIEVED. Eighteen comparisons became resolvable
across the three lineup policies, six stopped being
resolvable, and two k=7 point estimates fell outside their
k=5 intervals.

The two that matter most:

  * `mfl_8 real - adp` resolves at +82.07 [+13.54,+150.59]
    under the prior lineup and +95.74 [+23.26,+168.23]
    under hindsight, in a market whose null control is
    clean. It is the first time the arm that runs the
    cockpit has beaten the ten-line skill baseline
    resolvably in any market.
  * `mfl_12`'s long-standing G6a null-control FAILURE
    CLEARS. `bot` was +22.05 [+6.69,+37.40] at k=5 and is
    +24.82 [-0.31,+49.96] at k=7. All three markets now
    pass every gate.

Neither is safe on its own and section "How much to
believe" says why.

## Task 1 — the probe

### Outcome, nflverse `player_stats`

```
  season   rows  players  reg weeks
  2019    17362     1891   1-17 (17)
  2020    17602     1995   1-17 (17)
  2021    18969     2088   1-18 (18)
  2022    18831     2011   1-18 (18)
  2023    18643     1948   1-18 (18)
  2024    18983     2002   1-18 (18)
  2025    19422     2025   1-18 (18)
```

Both pinned and clean. NOT NOTED BY THE HANDOFF and worth
stating: 2019 and 2020 are SEVENTEEN-game regular seasons
and 2021 onward are eighteen. `bootstrap_weeks` replays a
player's own observed weeks, so it is not a scoring bug,
but the two new seasons carry one fewer game of outcome
than the five old ones.

### Projection, FFA vintage

`rec` and `rec_sd` are present in **2024 and 2025 ONLY**,
absent from 2018, 2019, 2020, 2021, 2022, 2023 and 2026.

THE HANDOFF SAYS THEY ARE "absent from 2021 and 2023".
That is wrong, and `sim/configs/b10-ffc.toml` already
recorded the correct version. It blocks nothing: under
`historical_deltas` a reception is worth 0.0 in this
league, and `assert_scoreable` reads the EFFECTIVE weights
rather than a season list.

Usable season set per league, measured:

```
  espn_davis_drive as configured      2024, 2025
  espn_davis_drive historical_deltas  2018-2025 (all)
  sleeper_boyfun   either             NONE, any season
```

`sleeper_boyfun` is refused in every season for a
different reason -- FFA carries no `def_st_ff` and the
other IDP columns that league scores. That is a standing
fact, not a B15 one.

### Market

Both sources reachable and both fetched. `sim/ffc.py` is
new: this repo had NO FFC fetcher, so the five original
pins came from outside it and two more added by hand would
have been the only seasons nobody could re-derive. It pins
the whole response, shape-checked, into `SIM_CACHE` and
never the cockpit's root.

The `teams` parameter is IGNORED for a past season --
measured on 2021, `teams=8` and `teams=12` return
byte-identical bodies both reporting `meta.teams = 12`,
both matching the committed pin. That is the twelve-team
confound `sim/markets.py` exists to size, and it means the
new pins are reproducible from either value.

MFL join rate against the FFA stat lines:

```
  fcount=8    2019 1.000  2020 1.000
              2021-2025 0.960-1.000
  fcount=12   2019 0.952  2020 0.938
              2021-2025 0.926-1.000
  unknown ids: ZERO in every season
```

FFC boards:

```
  season  rows  drafts  window            kickoff  margin
  2019     193     696  09-02..09-04      09-05     1 day
  2020     226    2667  08-25..09-01      09-10     9
  2021     224    2656  08-28..09-01      09-09     8
  2022     195    2534  ..09-04           09-08     4
  2023     192       -  ..09-01           09-07     6
  2024     180       -  ..09-01           09-05     4
  2025     221    2017  ..09-01           09-04     3
```

2019 IS THE THINNEST AND THE TIGHTEST. 696 drafts against
about 2,600, and a window closing ONE DAY before kickoff
-- the smallest margin of any season in any market. It
passes `assert_pre_draft`, which runs live on this path,
and the review confirmed forcing `asof = kickoff` raises
from inside `simulate_draft`. But it is a one-day margin
and it is reported rather than smoothed. Its 193 rows sit
inside the existing 180-226 range; 2024 is smaller.

### The room — the actual limit

League 6012 has completed drafts for **2021-2025 only**,
128 picks each. They cannot be fetched for earlier years:
the league's own history is the limit.

So `room.SEASONS` stays five and `room.RUNNABLE_SEASONS`
is seven. The opponent model is fitted on five seasons and
applied to seven.

### Pool margin

```
  season  pool  QB/RB/WR/TE/K/DEF
  2019    1179  158/291/422/218/57/33
  2020     596   85/145/176/118/40/32
  2021     623   85/144/209/121/32/32
  2025     588   76/129/193/121/37/32
```

No collapse. 2019 is LARGER than every other season, for
a reason worth its own section.

## The 2019 file carries 2020 information

2019 ships 2,238 rows for 1,661 distinct ids, a 26%
duplication rate against 4-28 duplicate rows elsewhere.
`ffa.read_raw` already dedups on id, first row wins, and
its docstring already names 2019 -- so this was known.

WHAT WAS NOT KNOWN is what the duplicates are. They are
the same player under two TEAMS, and the second team is
next year's:

```
  id 5848  Tom Brady      QB  NE  and TB
  id 7394  Philip Rivers  QB  LAC and IND
```

Both moved in the 2020 offseason. Measured across the
file: 568 duplicate groups, 560 disagreeing on team, and
**187 whose second row names a team that player first
occupied in a LATER year**. Of 176 datable labels, 169 are
first real in 2020 and 7 in 2021; none point past that.
The file was assembled in the 2020 league year.

`assert_vintage` PASSES it, and cannot do otherwise: it
checks the following year's DRAFT CLASS and this is
following-year FREE AGENCY. The docstring calling it "the
only thing standing between this dataset and a silent
leak" overstates what it guarantees, and 2019 is the
counterexample.

IT REACHES NO NUMBER, on four independent measurements:

  * `board_key` is `P:{normalized name}` for every
    non-DEF position, so team is not in the join key for
    skill players.
  * First-row-wins keeps the correct-for-2019 team in 183
    of 187 groups. All four exceptions are off-board --
    none is in the 193-row FFC board, let alone the 128
    drafted.
  * 2019's join rate is 0.995 / 0.997 / 0.996 across the
    three markets, the best or near-best of any season,
    and 127 of 128 in the top 128.
  * Stat lines are identical between duplicate rows except
    nine groups, seven of them IDP and irrelevant here.

WHAT IS STILL UNESTABLISHED, and is the honest residual:
nothing here shows the 2019 projection VALUES are
vintage-2019 rather than regenerated. The team labels date
the assembly to 2020; the numbers are not dated by
anything. That is an exposure, not a moved number, and it
is 2019-only.

Also 2019-only: FFC spells Jacksonville's defence `JAX`
and FFA spells it `JAC`, so `DEF:JAX` does not join. It
costs nothing -- DEF is a `ZERO_POSITION` scored zero on
both sides -- and it is unmeasured elsewhere.

## The extrapolation cost, measured

Leave-one-season-out: refit on four, draft the fifth,
ask whether the synthetic 5th-95th band COVERS that
season's real value. `covers`, not `passes` -- the
in-sample form demands a mean equal one integer and, in
`room.py`'s own words, "is not a test, it is arithmetic
that always fails". I ran `passes` first and got 0/5 on
everything; that number was meaningless and is recorded
here so nobody repeats it.

```
  statistic            ffc_12  mfl_12  mfl_8
  first QB round         5/5     4/5    5/5
  first K round          4/5     4/5    5/5
  first DEF round        4/5     4/5    4/5
  K+DEF in 128           4/5     3/5    5/5
  runs of 3+             5/5     5/5    5/5
  pick-ADP spread        3/5     1/5    0/5
```

`pick-ADP spread` does not survive in any market, and
mfl_8 fails it IN-SAMPLE too, so that part is a
pre-existing weakness rather than an extrapolation cost.

AND LEAVE-ONE-OUT FLATTERS THIS. Three of five folds hold
out an INTERIOR season and refit on four surrounding it,
which is interpolation. In ffc_12 the two spread misses
are exactly the two ENDPOINT folds, 2021 and 2025: 3/3
interpolating, 0/2 extrapolating. 2019 and 2020 are one
and two years further outside that hull than 2021 is.

Corroborating: the room's fitted `mu` trends over the fit
window in ffc_12 -- RB -3.64 picks a year (t = -4.01), WR
+2.93 (t = +8.75), both significant at 3 df. Holding a
pooled constant back to 2019 is off the trend line by
about 2.4 and 2.5 per-season standard deviations. Neither
MFL market shows a significant trend.

So the extrapolation is not free, it is worse than the LOO
table alone suggests, and it is the single largest
qualification on every k=7 number here.

## Task 2 — k=5 against k=7

Runner comparisons plus arm levels, three lineup policies,
three markets. Every one is reported, both directions.

```
  newly resolvable        18
  no longer resolvable     6
  k=7 estimate outside
    its k=5 interval       2
```

### The headline comparisons, prior lineup

```
                      ffc_12            mfl_12            mfl_8
  real - adp k5   +49.3 [-61.9,+160.6] +77.8 [-26.1,+181.8] +53.7 [-25.5,+132.9]
             k7   +72.4 [-29.9,+174.6] +61.7 [ -6.7,+130.1] +82.1 [+13.5,+150.6]*
  real - ffa_base
             k5   +18.0               +47.2               +35.7
             k7   +21.2               +18.5               +17.9
  real - pts_greedy
             k5  +207.1              +197.8              +184.9
             k7  +213.0              +160.5              +170.6
  transform - ffa_base
             k5   -66.7 [-92.9,-40.5]* -68.8 [-114.5,-23.2]* -46.5 [-80.9,-12.0]*
             k7   -62.9 [-86.9,-38.9]* -51.3 [ -95.1, -7.5]* -48.6 [-81.5,-15.7]*
```

`real - adp` resolves in ONE market of three. `real -
ffa_baseline` resolves in none and its point estimate
FELL in two of three. `transform - ffa_baseline` stays
resolvable everywhere and stays negative, which is the
result those two sessions were chasing and did not move.

### What was lost

```
  [prior]     mfl_12 ceiling per-game vs total
              +41.36 [+15.24,+67.49] -> +28.29 [-13.31,+69.90]
  [prior]     mfl_12 transform - ffa_vor
              -84.92 [-141.24,-28.60] -> -54.80 [-118.07,+8.48]
  [prior]     mfl_12 bot (level)   THE G6a FAILURE, CLEARING
              +22.05 [+6.69,+37.40] -> +24.82 [-0.31,+49.96]
  [oracle]    mfl_12 points_greedy - adp
              -114.27 [-226.98,-1.56] -> -94.16 [-242.76,+54.45]
  [oracle]    mfl_12 ffa_baseline (level)
              +85.42 [+5.75,+165.08] -> +140.32 [-8.45,+289.09]
  [hindsight] mfl_12 bot (level)
              +28.10 [+19.31,+36.89] -> +27.55 [-3.05,+58.15]
```

All six are mfl_12. Two of them are the null control
losing resolvability, which is a GAIN dressed as a loss.

### Estimates outside their k=5 interval

```
  [hindsight] mfl_12 shuffle - bot  -335.97 not in [-332.15,-289.73]
  [hindsight] mfl_12 shuffle (level) -308.42 not in [-297.15,-268.53]
```

Both mfl_12, both hindsight, both the shuffle arm. Two
of 225 cells. Not nothing, and both in the market whose
seat bias is the known anomaly.

### Width, and why the narrowing is selective

```
  k7/k5 half-width ratio over 225 cells
    min 0.611  p10 0.645  median 0.876  p90 1.664  max 3.480
    WIDER at k=7: 41%
  fixed-sd prediction t(6)/sqrt(7) over t(4)/sqrt(5) = 0.745
```

THE MEDIAN IS 0.876 AGAINST A PREDICTION OF 0.745, AND
41% GOT WIDER. So this is not a uniform sqrt(k)
narrowing. The comparisons that gained sit at 0.61-0.80
-- the left tail. They are the cells where the two extra
seasons happened to be quiet, which is a selection effect
and is why the leave-one-season-out column below matters
more than the interval.

(The naive "share of season-mean variance" I reported
first gives 0.845 as the benchmark and is wrong twice:
it ignores that the t quantile moves too, and it is a
biased estimator. Both corrected here.)

### Between-season share, one-way random effects

b10-leak.md's definition, `tau^2/(tau^2 + sigma_w^2/n)`:

```
                          ffc_12   mfl_12   mfl_8
  real - adp      k5       91.9%    92.9%    89.2%
                  k7       94.7%    91.5%    91.5%
  real - shuffle  k5       92.6%    70.7%    75.0%
                  k7       93.0%    72.7%    69.4%
```

IT BARELY MOVES, AND THAT IS THE POINT. More seasons do
not reduce the between-season SHARE -- it is a property of
tau and sigma_w. They narrow the interval by shrinking
`tau/sqrt(k)`. The handoff's framing, that 86.7% is
between-season and "only seasons reduce it", is right
about the remedy and wrong about the mechanism: seasons
reduce the interval, not the share.

## How much to believe: leave-one-season-out

Every newly-resolvable result, re-tested by dropping each
season in turn and recomputing at six clusters:

```
  survives 7/7   ffc  ceiling vs hindsight_points [oracle]
                 ffc  transform - points_greedy [hindsight]
                 mfl12 ceiling vs h_points [prior, oracle]
                 mfl12 adp (level) [prior]
                 mfl12 ceiling per-game vs total [oracle]
                 mfl8 ceiling vs h_points [oracle, hindsight]
                 mfl8 real - adp [hindsight]
  survives 4/7   ffc  transform - points_greedy [oracle]
                 mfl12 real - adp [oracle]
                 mfl12 ceiling vs h_points [hindsight]
                 mfl8  transform - points_greedy [oracle]
  survives 3/7   mfl8  real - adp [prior]
  survives 2/7   ffc  transform (level) [oracle]
                 mfl8  ffa_baseline (level) [prior]
  survives 1/7   ffc  transform - points_greedy [prior]
                 ffc  ceiling per-game vs total [prior]
```

**THE HEADLINE SURVIVES 3 OF 7 UNDER THE PRIOR LINEUP AND
7 OF 7 UNDER HINDSIGHT.** `mfl_8 real - adp` is fragile on
the primary measure and robust on the secondary one. Read
it as suggestive rather than established.

Subtracting the null control changes nothing for it:
+82.07 [+13.54,+150.59] becomes +85.95 [+21.73,+150.17].
`real` and `adp` both sit in seat 6, so the slot effect
enters both and cancels. Where it does NOT cancel is the
LEVELS: `mfl_12 adp (level)` goes from +81.20
[+29.20,+133.19] to +56.37 [-0.16,+112.90], so 30% of
"adp beats the field" in that market is the draft slot.

Also: `adp` and `adp_board` are the same series to
0.000000 on every unit. Counting both inflates any tally.

## Task 3 — the two dead levers at k=7

### The control variate: still dead, and slightly worse

Break-even falls from 0.655 to 0.495 at k=7 and eight of
eighteen comparisons now clear it. It does not matter,
because the anti-conservatism is a property of the
ESTIMAND rather than of k. Coverage of a nominal 95%
interval for the season mean:

```
  rho    0.00  0.50  0.66  0.80  0.90  0.95
  k=5    .950  .929  .904  .848  .740  .607
  k=7    .950  .923  .892  .821  .683  .536
```

WORSE AT EVERY NONZERO RHO. And the lower threshold makes
the bad gate EASIER to clear: a zero-information covariate
clears it 25.9% of the time at k=7 against 22.9% at k=5.

`sim/test_g_b14.py` is unchanged from `main` -- the diff
is zero bytes -- and its deciding coverage gate still
passes. The lever stays retired.

### Depth: k=7 answers what k=5 could not

Both candidate rules re-run at seven seasons, paired on
the same units, on the `real` arm. The rules were reverted
and are not in the code, so the DEPTH TABLE each produced
is forced directly rather than the rule reimplemented from
prose.

```
                    ffc_12              mfl_12            mfl_8
  a73 - main    -9.69 [-17.56,-1.82]* -1.80 [-13.8,+10.3] -0.21 [-10.0,+9.6]
  a79 - main    +1.00 [-14.95,+16.94] +1.68 [ -5.1, +8.5] +3.07 [ -2.8,+8.9]
  a79 - a73    +10.69 [ -2.88,+24.25] +3.47 [ -7.6,+14.5] +3.28 [ -8.0,+14.5]
```

`a73` is audible#73/#78's rule, QB 14 / RB 43 / WR 35 /
TE 20, distance 27.2 from the league. `a79` is
audible#79's, QB 8 / RB 46 / WR 38 / TE 20, distance 31.2.
Main is 37.2.

**THE RULE TWO SESSIONS SPENT THEMSELVES BUILDING IS
RESOLVABLY WORSE THAN MAIN IN ffc_12, by -9.69
[-17.56,-1.82].** At k=5 that comparison could not be
resolved either way. Seven seasons turn "no measurable
difference" into "measurably worse in one market", and the
direction is the opposite of what the depth line was
chasing. `a79` is null everywhere and `a79 - a73` remains
unresolvable, as it was at k=5 (+0.25 [-9.53,+10.04]).

## What this session got wrong

**The prior refit, and it was fatal until a review caught
it.** The first version changed `_prior_for`'s season set
from `room.SEASONS` to the run's own seasons, with a
comment asserting those are identical for every config in
the repo. `b4-smoke.toml` and `b4-transform.toml` are
FOUR-season runs. Re-running `b4-smoke` moved every one of
eleven arms and `real - adp` went from -17.08 to -30.53.
Nothing in the suite caught it: no test re-runs a b4
config and compares numbers, and the committed checkpoints
are complete so `--resume` replays the old rows and
reproduces the old artifact.

It also confounded the thing this session exists to
measure. At seven seasons the 2021 prior saw 2019 and
2020, so 1,153 to 1,252 of the 3,900 shared units changed
`points_for` and the k=5-against-k=7 delta stopped being
"two more seasons". Reverted. Every 2021-2025 unit is now
byte-identical between the two runs -- 0 of 3,900 differ
-- and `test_the_k5_units_are_untouched_by_the_extension`
is the gate that catches it, verified against the mutation.

THE FIRST-VERSION NUMBERS WERE DIFFERENT AND WORSE-FOUNDED.
`mfl_12 real - adp` read +70.25 [+1.00,+139.51] under the
confounded run and is +61.66 [-6.74,+130.06] corrected. It
does not resolve. Anything quoting that +1.00 lower bound
is quoting the artifact of a refit.

**`passes` instead of `covers`** on the held-out room
test, which the code says always fails on a single season.
Corrected above.

**Three comment defects**, all mine, all corrected:
"absent from six of these eight" when the tuple has seven
entries and the column is absent from five; "five of six
statistics survive" stated without the market qualifier
when `first DEF round` is 4/5 in both MFL markets; and a
test helper taking a fixture argument it ignored, with a
docstring describing behaviour it did not have.

**`sim/runs/b15-seasons.md` was cited in six places before
it existed.** This file.

## Standing caveats, carried forward

`real` comparisons are paired on seeds and the room but
NOT on conditions: the room is reactive, so two arms
differing at pick 3 face different opponents from pick 4
on. Pairing reduces variance and does not remove bias.

`ffc_12` releases the first quarterback 5.76 picks early
against a real mean of 27.0, cause unexplained after three
refuted hypotheses in `b10-leak.md`.

The room is fitted on five seasons and applied to seven,
and the extrapolation section above is why that is the
largest qualification here rather than a footnote.

## G16 did not hold, and B15 did not cause it

The handoff pins the live cockpit cache at 63 files with
combined sha256 `5cf13da7635b628b`. Measured at the end of
this session: 63 files, sha256 `ec98ea24e69829c9`.

The difference is exactly one file.
`data/cache/sleeper_players_nfl.json` was rewritten during
the session, at 18:29:34, and it is a valid catalog --
12,226 entries, correct shape. Only its content changed;
the file count did not.

NOTHING IN B15 WRITES THERE. `sim/ffc.py` writes into
`SIM_CACHE` and nowhere else; `sim/mfl.fetch` writes into
`SIM_CACHE/mfl`. Both were checked at the call site.

WHAT DOES. `SleeperAdapter.__init__` defaults its cache to
`JsonCache()`, whose root is `DEFAULT_CACHE_DIR` -- the
COCKPIT'S cache. `tests/test_adapters.py` and
`tests/test_sleeper_scoring_drift.py` construct bare
`SleeperAdapter()` instances, and `get_players_catalog`
refreshes on a daily TTL. So the default test suite
rewrites a live cockpit file once per day, on whichever
run first crosses the TTL boundary.

It reproduces exactly that way: re-running the default
suite and the sim slow suite immediately afterwards leaves
the file byte-identical, because the entry is now fresh.
That is why the write is invisible on any single run and
why no gate has caught it.

`sim/test_g_cacheroot.py` asserts the SIM's root is not
the cockpit's and is not under it. Nothing asserts the
same of `tests/`. That is the gap, it is pre-existing, and
fixing it is a change to `tests/` which this session is
not authorised to make.
