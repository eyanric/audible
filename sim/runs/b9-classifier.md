# B9 — the classifier, and validation per market

VERDICT: 1 of 3 markets has a fully valid room.

Branch `feat/sim-classifier`, off `main` at `48d9f67`.
Nothing merged.

The classifier is replaced and now derives `{DEF, K}` in
all three markets, so the B8 defect that took running
backs and receivers off the MFL eight-team board is gone.
Room validation is parameterised over every declared
market, and the answer it gives is that only FFC's room
passes B1. Both MFL rooms miss one pre-registered
statistic each, and each still fails one run gate.

Two premises in the handoff are refuted below, and one of
this session's own fixes was refuted by adversarial review
before it shipped.

---

## Task 1 — the classifier

`clock_ratio = sd(pick) / sd(pick - rank)`, cut at 1.0,
below the cut is the schedule clock.

```
ffc_12   K 0.602  DEF 0.409  WR 1.847  RB 1.965
         TE 1.866  QB 2.240  -> {DEF, K}
mfl_12   K 0.299  DEF 0.258  WR 1.505  RB 2.175
         TE 1.961  QB 1.640  -> {DEF, K}
mfl_8    K 0.368  DEF 0.323  WR 1.406  RB 1.687
         TE 1.923  QB 1.583  -> {DEF, K}
all three derive {DEF, K}: yes
```

Separation, worst case over all three markets: nearest
board position WR 1.406 on mfl_8, nearest scheduled K
0.602 on ffc_12, a factor of 2.34. The retired supply
ratio managed 1.005 on mfl_8, on the wrong side of its
own cut.

Stability: pooled derives `{DEF, K}` in all three, and so
does every one of the fifteen leave-one-season-out fits.
Single seasons do not, and the code says so rather than
guessing — see the sample floor below.

### Why this one is not refuted the way the other two were

The cut has a closed form nobody had written down. With
`k = sd(rank)/sd(pick)` and `rho = corr(rank, pick)`:

```
ratio > 1  <=>  k < 2*rho  <=>  slope > 0.5
```

where slope is the OLS slope of pick on rank. The
correlation cancels out entirely. So the classifier is a
slope test with the cut at half a pick per rank, which is
the cleanest answer to "why is this not the correlation
test again": it is not a function of rho at all. Verified
on all eighteen market-position cells, zero mismatches.

REFUTATION 1, rescaling. The correlation test died
because it could not SEE the 8/12 rescaling — r agrees to
six decimal places under it. This statistic is not
invariant, which is the point. Verdicts hold at every
c from 0.5 to 1.0, and at c = 2/3, the rescale the
two-clock story is actually about, every margin improves.
The flip point is c* = 2*slope, and the nearest board
position is WR on mfl_8 at c* = 1.241. Asserted.

REFUTATION 2, range restriction. IT PARTLY LANDS, and the
handoff's claim of "no range-restriction problem" is
wrong. Restricted to the specialists' own rank-and-pick
box, EVERY position reads below the cut — QB 0.42, RB
0.52, WR 0.47, TE 0.66 against K 0.37, DEF 0.32 on mfl_8.
It is mechanical: the box is ~46 picks wide and 120-206
ranks wide, so k is inflated by its aspect ratio and
everything is pushed under the cut by construction. The
consequence is a rule rather than a caveat — the cut is
meaningful only on a position's unconditioned
population, which is what `fit_room` uses. Recorded as a
gate so nobody adds a conditional later without finding
out what it costs.

### How close the nearest market is to failing

Reported because "it works on three" is not "it works".
The binding cell is WR on mfl_8: sd(rank) 47.17 against a
limit of 2*rho*sd(pick) = 58.56, so 19.4% of headroom,
bootstrap interval [1.217, 1.640], 0 of 10,000 resamples
below the cut. Comfortable here, and not a large margin
in general: the observed between-market spread in
sd(rank) for receivers is 37.5 to 47.2, a 26% range,
which already exceeds the headroom left. A fourth market
landing under the cut is not remote, and it would show up
as a receiver being scheduled.

Board DEPTH does not drive it, which was the obvious
guess and is wrong. mfl_12 serves 289-312 rows against
mfl_8's 219-241 and has the BETTER receiver margin.
Truncating the room to eight rounds against the same
board leaves every skill ratio between 1.10 and 2.31.
What drives it is the rank scatter of the drafted set.

### The sample floor, bracketed rather than chosen

`MIN_CLOCK_N` was 10 and 10 was calibrated to the wrong
thing. Measured:

```
single-season fits   thinnest n 6-8, QB n 12-14
leave-one-season-out thinnest n 27-32
pooled five-season   thinnest n 34-41
```

At n=12-14 the quarterback crosses the cut on both MFL
markets, clears a floor of 10, and is scheduled — which
removes every QB from the board in a one-QB league. That
is the B8 catastrophe, reproducible from a config
`load_config` accepts. Leave-one-out must be admitted
because `room.holdout` is a real code path.

So any floor in (14, 27] does the same job. It is set to
20, and a gate asserts that every floor from 15 to 27
gives the identical pooled and held-out verdict in all
three markets — which is the difference between
bracketing a constant and tuning one.

---

## Task 2 — validation per market

`python -m sim.room --market`, `sim.inv_run --market`,
and `sim/test_g_room.py`'s fixture parameterised over
`markets.REGISTRY`. `B1_SCHEDULED` is gone; both sides of
the G7 gate are now derived — `expected_scheduled()` from
the league's starting slots, `fit.scheduled` from picks
and ranks.

```
B1 battery, in-sample / held-out, SEEDS=50
  ffc_12   6/6 pass, 28/30 covered  -> resembles real
  mfl_12   5/6 pass, 25/30 covered  -> does not
  mfl_8    5/6 pass, 24/30 covered  -> does not
```

mfl_12 misses `first QB round`: synth 2.96 against a real
range whose floor is 3.0. That is 0.04 of a round, and it
is the only thing between that room and a pass.

mfl_8 misses `pick-ADP spread`: synth 20.3 against a real
23.2-26.8. Note the direction — under B8's classifier the
same statistic read 51.2, three times too WIDE, at -87
sem. The fix moved it to -29 sem and from three in-sample
failures to one.

The spread is the statistic sigma is FITTED to. It is the
member that misses in every market's held-out grid, and
`report()` already labels it a self-consistency check
rather than evidence.

### An honest limit on how derived the gate really is

`expected_scheduled()` reads `room.STARTING_SLOTS`, a
module constant, not `config.league`. `fit_room` always
joins against `espn_draft_6012_*` whatever a config says.
So "two independent sources" means two files describing
ONE league, not two leagues. The gate catches a
classifier that drifts — which is what B8 needed and did
not have — and would NOT catch a league whose roster this
module does not model. `load_config` refuses any config
whose league is not the market's declared league, which
is what keeps that latent rather than live.

---

## Task 3 — G6a on mfl_12: the premise is refuted

```
G6a mfl_12: bot in seat +22.0 [+6.7, +37.4]
  cause: NOT a machinery asymmetry. The gate's own
  premise does not hold, and the excess does not
  replicate.
```

The `bot` arm is `simulate_draft(board, fit, seed)` with
NO chooser and NO chooser_seat, so all eight seats run
identical code and no seat can be privileged by
construction. Every seat finishes with exactly 16.00
scoreable players, so the `audible#71` defect is fully
fixed and is not recurring.

Two reasons the premise fails:

A snake draft gives every seat the same SUM of pick
numbers — the +8s the odd rounds hand seat s are
cancelled by the -8s the even rounds take back — but not
the same DISTRIBUTION. Seat 1 takes picks 1 and 16 where
seat 8 takes 8 and 9, and draft value is not linear in
pick number.

And the statistic is a CONTRAST: seat minus the mean of
the other seven. The eight are algebraically constrained
to sum to zero. "The eight average to zero" is
guaranteed; "seat 6 is zero" is implied by nothing.

Measured at every seat, with the harness's own
leave-one-out prior and its own season-clustered
interval:

```
seeds 0-59
  ffc_12   0 of 8 seats exclude zero, spread 17.8
  mfl_12   1 of 8 (seat 6, +20.67 [+1.85, +39.48])
  mfl_8    0 of 8, spread 37.7

seeds 500-559, disjoint
  ffc_12   1 of 8 (seat 1, -30.96)
  mfl_12   0 of 8  seat 6 = -5.50 [-26.94, +15.93]
  mfl_8    0 of 8
```

Seat 6's excess does not replicate. It flips sign. Across
both seed sets that is 2 exclusions in 48 seat-market
tests, 4.2%, which is what a 95% interval is supposed to
produce. A machinery asymmetry favouring the measured
seat would appear in every market; it appears in one, at
one seat, marginally, once.

The gate is NOT adjusted. It is reported.

---

## Task 4 — the arms, per market

```
transform - adp, prior lineup
  ffc_12   -35.4 [ -94.2, +23.4]
  mfl_12   -38.2 [-141.1, +64.8]
  mfl_8    -28.5 [-149.8, +92.8]
  sign survives corrected classifier: yes

transform - adp, oracle lineup
  ffc_12   -40.4   mfl_12  -70.9   mfl_8  -70.1
transform - adp, hindsight lineup
  ffc_12   -43.5   mfl_12  -85.1   mfl_8  -60.0
```

Negative in all three markets under all three lineup
policies, nine of nine. None resolvable. The standing
result holds.

What DID move, and only on mfl_8, which is the only
market whose classifier changed:

```
transform - points
  ffc_12   +122.3 [-66.5,+311.2]   B9 = B8
  mfl_12    +81.7 [+12.1,+151.4]   B9 = B8
  mfl_8    +102.7 [ +4.1,+201.3]   B9
           -97.1 [-161.9, -32.2]   B8
```

A resolvable sign reversal, and it confirms B8's
withdrawal on a full run. B8 measured a counterfactual
at 20 seeds that predicted +87.9 [-13.0, +188.8]; the
60-seed run with the corrected classifier gives +102.7
[+4.1, +201.3]. All three markets now agree in sign.

`transform - ffa_baseline` is resolvably negative in all
three (-66.7 / -68.8 / -46.5), so B5's finding that FFA's
replacement depth beats ours strengthens.

ffc_12 and mfl_12 reproduce B8 to the digit, which is the
control: the classifier change is a no-op exactly where
the old classifier was right.

Run gates: b9-ffc all pass. b9-mfl8 now PASSES G7 and
fails G6b (`real - shuffle` +68.2 [-28.3, +164.6]
includes zero). b9-mfl12 fails G6a as above.

---

## Injections

17 of 18 fire. The one that does not is `adp-only` on
mfl_8, and the handoff's injection 3 — "adp-only room ->
G3-equivalent fails in every market" — is refuted.

```
injections 1-5: fired in all markets except
  adp-only on mfl_8_std, which cannot
```

The injection reproduces a room that drafts strictly by
ADP and collapses the specialists. On FFC's twelve-team
board that collapse is total, because its top 128 holds
NO KICKER IN ANY SEASON. On MFL's eight-team board strict
ADP takes 11-16 specialists against a real 16-17 and
lands inside the range, so there is no defect there to
reproduce.

Read plainly: the pick schedule exists to correct a
board/room TEAM-COUNT MISMATCH. Where the market already
matches the league, the correction is not doing much.
That is the same fact as the supply ratio's degeneracy,
seen from a third angle, and it is a limit on injection
coverage in that market rather than something to fix.

---

## What adversarial review found in this session's work

D1, a hard defect, fixed. G7's message builder did
`f"{value:.3f}"` on a clock ratio, but `fit_room` writes
`inf` for an unclassified position and `artifact._clean`
turns that into the STRING "inf" to keep the payload
JSON-safe. The format raised ValueError, and because
`gate_failures` is called bare that aborted the ENTIRE
gate list — G0, G5, G6a, G6b and G9 never evaluated. The
run died on a traceback in exactly the configuration that
most needs a gate. Reachable from a config `load_config`
accepts. Now formatted defensively, with a regression
gate.

D2, fixed. `MIN_CLOCK_N` at 10 admitted the n=12
quarterback; see the bracket above. My first fix for this
was itself refuted: I gated classification on a bootstrap
interval clearing the cut, which is the more principled
rule and is unusable at these sample sizes — at n=27, the
thinnest cell leave-one-out uses, FFC's kicker reads a
point estimate of 0.600 and still resamples above 1.0
more than one time in forty, so `holdout` lost the kicker
to the board clock and two of fifteen fits went red. The
bootstrap is now reported and does not decide.

D3, fixed. The rescaling test probed only c <= 1.0, every
value of which is on the safe side by construction, so it
could not fail. It now asserts the flip point.

D7, fixed. A docstring cited ffc 2024 K = 1.982 as what
the code produces. It is not — under the sample floor
that cell is unclassified, and the real single-season
verdict is an empty scheduled set. A wrong comment is a
defect.

Also recorded and not fixed: `SPECIALIST_POSITIONS`
cannot contain IDP, so an IDP league's G7 would be
unsatisfiable without editing that literal; and the
walk-forward split's room structure is ungated, because
only the main fit reaches `artifact.fit_block` (measured,
it agrees on all three markets, so no live defect).

---

## Gates

```
G1  classifier derives {DEF, K} in all three: yes
G2  B1 battery per market: reported above
G3  G6a mfl_12: cause named, premise refuted
G4  no market literal decides anything: gated
    behaviourally, not by grep
G5  17 of 18 injections fire; the hole is named
G6  assert_pre_draft guards every board in every
    market: yes
G7  determinism per market: digests reproduce
G8  live cache untouched: 63 files
G9  default run 556 passed, 1 xfailed: unchanged
G10 sim gates: 401 passed (286 in B8; the room
    battery is now three markets, plus B9's own)
G11 no CSV committed: 0 tracked
G12 test_g_b8 vintage gate skips: no
```

G12 was fixed by moving the gate off the gitignored
subscription CSV and onto `nflverse/ff_playerids`'s
`draft_year`, which is re-fetchable from an open source
and already the first entry in `required_inputs`. The two
sources return the same verdict on all twelve
market-seasons where the CSV is present, and the CSV is
kept as a corroboration test that is allowed to skip
because it is not the gate.

---

## What this does not say

It does not say the two MFL rooms are usable. They are
not: one misses first-QB-round by 0.04 of a round and the
other under-disperses the spread, and each still fails a
run gate.

It does not say the classifier is safe on a market nobody
has run. The nearest board position sits 19.4% from the
cut and the between-market spread already exceeds that.

It does not identify a cause for mfl_8's G6b. `real -
shuffle` fell from +104.5 [+34.3, +174.8] under the
broken room to +68.2 [-28.3, +164.6] under the corrected
one. That is the leak detector becoming inconclusive in
the market whose room changed, and it is UNRESOLVED.

Five seasons remains five. Every interval has four
degrees of freedom.
