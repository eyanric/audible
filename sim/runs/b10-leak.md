# B10 — the leak detector and the scale mismatch

VERDICT: mfl_8's leak detector is a SEASON-COUNT power
shortfall, not a defect and not an absent effect;
1 of 3 markets is trustworthy, and it carries a bias
nobody had measured.

Branch `feat/sim-leak`, off `main` at `f75a855`.
Nothing merged.

Three premises are refuted below. One of them is mine:
the fix I wrote for Task 3 shipped a regression, was
caught by adversarial review, and is reverted.

---

## Task 1 — mfl_8's G6b

The interval is an ANALYTIC CLUSTERED t, not a bootstrap.
`seat.mean_and_interval` takes the five season means,
their sample sd, divides by sqrt(5) and multiplies by
t(4) = 2.776. Nothing resamples. (The word belongs to
`weekly.bootstrap_weeks`, which resamples a player's
observed weeks; several reports have conflated them.)

So seeds enter only through how noisy each season mean
is, and the asymptote is t(4)*tau/sqrt(5).

```
real - shuffle, one-way random effects
              tau   sigma_w  between   half(60)  half(inf)
  ffc_12     16.4     207.4    27.2%      39.0      20.3
  mfl_12     54.7     214.8    79.5%      76.0      67.8
  mfl_8      72.5     219.4    86.7%      96.5      89.8
```

mfl_8's asymptote is 89.8 against a mean of 68.2. The
shortfall is about 22 points and at most about 7 are
available from seeds at any count.

MEASURED, running the arms at four seed counts:

```
  seeds  60  +68.16 [-28.29, +164.61]  half  96.45
  seeds 120  +70.72 [-27.24, +168.67]  half  97.95
  seeds 240  +67.30 [-33.87, +168.48]  half 101.17
  seeds 480  +66.02 [-33.88, +165.93]  half  99.91
```

Eight times the seeds and the half-width does not
shrink. No seed count suffices.

### The per-season detail, which is the actual content

```
real - shuffle by season
             2021    2022    2023    2024    2025
  ffc_12   +120.5  +117.0  +109.6   +95.7   +43.8
  mfl_12    +57.6   +74.1  +120.6   +19.3  +178.0
  mfl_8     +47.8   +93.4   +88.2   -50.1  +161.4
```

In 2024 on mfl_8 the SHUFFLED board beat the real one.
That season alone is 58% of the width; with 2025 it is
94%. ffc_12 resolves not because its effect is bigger
(97.3 against 68.2, a factor of 1.43) but because its
between-season sd is smaller (16.4 against 72.5, a
factor of 4.4).

### Why it is not a defect

The 2024 excursion hits `real` (-43.2) and the NULL
CONTROL `bot` (-45.1) together while `shuffle` (+6.9)
and `adp` (+57.2) are unremarkable. That looked like a
seat/room shock. It is not: measured at every seat in
every season and market, the bot advantage has sd 26.9
over 120 cells, and mfl_8's 2024 seat 6 reads -45.1,
which is z = -1.67 and the 7th percentile. Seven cells
are worse, in all three markets. Every season's eight
seat advantages sum to exactly 0.00, as the contrast
requires.

So it is an ordinary seat-season draw that the paired
`real - shuffle` difference happens not to cancel.

### REFUTATION of my own framing

"SIGNAL, not power" is a category error and adversarial
review was right to say so. At infinite seeds the test
reduces to a one-sample t on five season means:

```
  ffc_12   t = 13.29 on 4 df   p = 0.0002
  mfl_12   t =  3.68 on 4 df   p = 0.0211
  mfl_8    t =  2.11 on 4 df   p = 0.1029
```

p = 0.103 is a power shortfall in SEASONS, not evidence
the effect is absent. The codebase already says exactly
this -- `runner.py` prints "Add SEASONS, not seeds" and
`seat.mean_and_interval`'s docstring says the limit is
the number of markets. mfl_8 first resolves at EIGHT
seasons. There are five.

Also worth stating: the season-clustered estimand asks a
RANDOM-season question. Under a FIXED-season estimand
mfl_8 reads +68.2 [+43.3, +93.0] and excludes zero, as
do all three markets. A leak is a code property and must
appear in every season, so for G6b specifically the
fixed estimand is arguably the right one. The gate is
NOT adjusted -- that is a design question, not a repair
-- but the choice of estimand, not the detector, is what
is failing here.

---

## Task 2 — coherence

`fit_room` joins `espn_draft_6012_*` regardless of
config, and 6012 is eight-team. Verified: `TEAMS = 8`,
no call site passes `teams=`, and `expected_scheduled()`
reads a module constant.

```
first-QB pick bias against a real mean of 27.0
  ffc_12   -5.76 picks   (-0.72 rounds)
  mfl_12   -7.01 picks   (-0.88 rounds)
  mfl_8    -0.64 picks   (-0.08 rounds)
```

The round statistic hides this: it buckets by eight, so
a six-pick error still lands inside a five-season min-max
of [3, 5], and ffc_12 passes at +1.2 sem -- inside the
module's own marginal band.

**ffc_12 releases the first quarterback most of a round
early, and every headline number this project has
published came from it.** That is the most important
thing in this report.

### REFUTATION of the explanation

The attractive story -- twelve-team board, eight-team
room, `mu` additive where the coherent map is
multiplicative -- is refuted three ways:

```
first-of-position bias, all three markets
             QB      RB      WR      TE       K     DEF
  ffc_12   -5.44   +0.50   -0.53   +1.46   +4.56   +1.77
  mfl_12   -7.11   +1.42   -1.34   -0.03   +7.30   +2.20
  mfl_8    -1.10   +0.71   -1.26   +7.07   +7.28   +2.62
```

The first KICKER is 4.6 to 7.3 picks early in ALL THREE
markets, the matched control included and worst. K is a
SCHEDULED position: `expected_pick` returns `pick_mu[K]`
and never reads a rank, and `pick_mu`/`pick_sd`
reproduce the real kicker mean and sd exactly. So the
same bias arises with a perfect location, a perfect
scale, and no rank-to-pick map at all.

Second, the measured slope of pick on rank does not
track team count: 0.886 on FFC's twelve-team board
against 0.741 on MFL's eight-team one. The twelve-team
board is CLOSER to 1.0, which is backwards.

Third, rescaling ranks by 8/12 and refitting moves the
matched control by +5.4 picks, about as much as it moves
the two mismatched markets.

What the evidence supports is that a first-of-position
statistic is a MINIMUM over roughly a dozen draws, so it
reads the left tail and a larger `sigma` pulls it
earlier. Halving `sigma[QB]` moves ffc_12's bias from
-5.4 to -1.4, a bigger lever than anything else tested.

**The bias is real and recorded. The explanation is
open.**

### Verdicts

```
  ffc_12   COHERENT WITH A STATED LIMITATION
  mfl_12   COHERENT WITH A STATED LIMITATION, the same one
  mfl_8    the control; its defects are different defects
```

Neither should be retired. They are the SAME construct
-- same league, same eight-team room, same treatment of
a twelve-team board -- so any argument against mfl_12 is
an argument against ffc_12, and ffc_12 is the only market
whose room passes B1. The limitation to state on every
result from either: the first quarterback goes most of a
round too early, and the cause is not established.

---

## Task 3 — the spread, and a regression I shipped

The handoff posed a dichotomy: the spread is a validation
statistic or a self-consistency check, and it cannot be
both. I acted on it, moving the three FITTED statistics
out of the in-sample verdict and gating them on held-out
coverage at three of five.

**That was a regression and it is reverted.** Adversarial
review measured a room whose K and D/ST schedule is a
FULL ROUND wrong -- `pick_mu` shifted by nine picks --
and the de-gated battery passed it on ffc_12, stable at
50, 100 and 200 seeds. The mutation parks all three
fitted statistics on exactly the bar, and the bar has no
margin.

The bar's input was also wrong. It came from
Binomial(5, 0.9) on the premise that the synthetic 5-95
percentile band delivers 90% coverage. `_pct` indexes at
`round(q*(n-1))`, so for a fresh continuous draw the band
covers (i95-i5)/(n+1): 0.692 at 12 seeds, 0.882 at 50 --
never 0.90. And five of six statistics are discrete, so
their bands are conservative at 0.92 to 1.00 instead.
There is no single p.

### What is true instead, and it is worse

`first_qb_round` was labelled `free` -- "the fit targets
nothing resembling it". It is not free.

```
  mu[QB] against mean(real QB pick - board rank)
  ffc_12   +6.3438  vs  +6.3438   identical
  mfl_12  +16.5077  vs +16.5077   identical
  mfl_8   +23.3077  vs +23.3077   identical
```

Shifting `mu[QB]` moves the statistic one for one. It is
structurally identical to `first_k_round`: a directly
fitted location plus an untargeted tail functional.

**So FOUR of the six are fitted, not three, and only
`kdef_in_128` and `runs_3plus` are untargeted.** The
dichotomy cannot be resolved as posed, because there is
no clean subset of untuned statistics to fall back to.
The label is corrected; the battery is not shrunk.

Per-statistic held-out coverage is now REPORTED beside
the grid, ungated:

```
  ffc_12   K+DEF 5/5  DEF 5/5*  K 5/5*
           QB 5/5*  spread 3/5*  runs 5/5
  mfl_12   ... DEF 4/5*  spread 1/5*
  mfl_8    ... DEF 4/5*  spread 0/5*
  (* = fitted)
```

mfl_8's spread covering 0 of 5 is stable at 12, 25, 50
and 100 seeds and is the sharpest single statement about
that market's fit.

---

## Task 4 — the arms, with leak status attached

```
leak detector, real - shuffle
  ffc_12   +97.3 [ +58.4, +136.3]   RESOLVABLE
  mfl_12   +89.9 [ +13.9, +165.9]   RESOLVABLE
  mfl_8    +68.2 [ -28.3, +164.6]   INCLUDES ZERO

transform - adp, prior lineup
  ffc_12   -35.4 [ -94.2,  +23.4]   [resolvable]
  mfl_12   -38.2 [-141.1,  +64.8]   [resolvable]
  mfl_8    -28.5 [-149.8,  +92.8]   [INCLUDES ZERO]

transform - adp, oracle lineup
  ffc_12   -40.4    mfl_12  -70.9    mfl_8  -70.1
transform - adp, hindsight lineup
  ffc_12   -43.5    mfl_12  -85.1    mfl_8  -60.0

transform - points
  ffc_12  +122.3 [ -66.5, +311.2]
  mfl_12   +81.7 [ +12.1, +151.4]
  mfl_8   +102.7 [  +4.1, +201.3]   [INCLUDES ZERO]

transform - ffa_baseline
  ffc_12   -66.7 [ -92.9,  -40.5]
  mfl_12   -68.8 [-114.5,  -23.1]
  mfl_8    -46.5 [ -80.9,  -12.0]   [INCLUDES ZERO]
```

`transform - adp` is negative in all three markets under
all three lineup policies, nine of nine, none resolvable.
Unchanged from B9.

Every mfl_8 number is marked, because its shuffle arm
cannot distinguish the real board from a randomised one.

---

## Gates

```
G1  mfl_8 G6b diagnosed: season-count power shortfall
G2  coherence answered for ffc_12 and mfl_12
G3  spread: taxonomy corrected, battery not shrunk
G4  classifier derives {DEF, K} in all three
G5  MIN_CLOCK_N bracket, NARROWED to (14, 20]
G6  range-restriction rule: recorded; the gate that
    actually enforces it is G7, not that test
G7  assert_pre_draft guards every board
G8  determinism per market: digests reproduce
G9  live cache untouched: 63 files
G10 default run 556 passed, 1 xfailed
G11 sim gates: 439 passed (401 in B9)
G12 no CSV committed: 0 tracked
G13 every split's room structure now gated
```

**G5 changed and it matters.** B9 asserted the bracket
was (14, 27], measured on the pooled and leave-one-out
windows only. Gating every split's structure made the
three-season walk-forward window a checked code path,
and FFC's walk-forward kicker joins exactly 20 times --
so a floor of 20 sat precisely on the binding edge. The
true bracket is (14, 20] and the floor is re-centred to
17. No verdict moves on any window in any market.

**G6 is a recorded caveat, not a gate.** B9's
range-restriction test never calls `fit_room`, so a
conditional added to the classifier would leave it
green. What catches that is G7 and the clock gates --
measured, a box-conditioned classifier derives
{DEF, K, WR} on ffc_12 and {DEF, K, RB, WR} on both MFL
markets, so four gates go red. The docstring claimed
enforcement it did not provide; corrected.

## Injections

```
1  shuffle reads the real board -> G6b fires, END TO END
   and in all three markets. B9's version checked the
   ARM in one market; it never checked the GATE.
2  restore SUPPLY_RATIO_CUT -> mfl_8 schedules RB, WR
3  MIN_CLOCK_N = 10 -> the n=12 QB is scheduled
4  leaky board -> assert_pre_draft raises everywhere
5  condition the classifier on the specialists' box ->
   caught by G7 and the clock gates
adp-only on mfl_8: cannot fire, by construction
```

---

## What this does not say

It does not say any market is trustworthy without a
caveat. ffc_12 is the only one whose room passes B1 and
it carries an unexplained one-round early-QB bias.

It does not explain the first-of-position bias. Three
candidate mechanisms were tested and refuted; a
minimum-over-draws tail effect is consistent with the
evidence and is not established.

It does not resolve mfl_8's leak detector. Eight seasons
would; there are five.

Five seasons remains five, and after B10 that is the
binding constraint on three separate results rather than
one.
