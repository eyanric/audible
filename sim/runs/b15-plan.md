# B15 pre-registration, committed before any season is pinned

Base `main` at 6a4f9253. Written and committed BEFORE a single
new season is fetched or pinned, so G1 is satisfied by commit
order rather than by assertion.

## What is under test

Whether extending the pinned set from five seasons to seven
resolves comparisons that are null at k=5. Nothing else changes:
no model code, no `replacement.py`, no `ordering.py`, no
estimator. The sample grows and everything is re-measured.

## The k=5 baseline, from audible#79, production board

Point estimates, paired on (season, seed), clustered on season,
prior lineup policy. All nine intervals include zero.

```
                        ffc_12   mfl_12   mfl_8
  real - adp             +49.3    +77.8    +53.7
  real - ffa_baseline    +18.0    +47.2    +35.7
  real - points_greedy  +207.1   +197.8   +184.9
```

Comparisons that ALREADY resolve at k=5 and must be re-reported
whatever happens to them:

```
  transform - ffa_baseline  -66.7  -68.8  -46.5   all resolve
  real - shuffle           +286.6 +367.7 +302.0   all resolve
  shuffle - bot             -99.1 -248.8 -169.8   all resolve
  bot (null control)         -4.1  +22.0  -10.0   mfl_12 resolves
                                                  and is the known
                                                  G6a failure
```

## Expected direction, stated in advance

  * `real - adp`, `real - ffa_baseline`, `real - points_greedy`:
    POSITIVE. If k=7 moves any of them negative, that is a
    finding against the arm and is reported as one.
  * `transform - ffa_baseline`: NEGATIVE, and expected to stay
    resolvable. If it stops resolving at k=7, the extra seasons
    disagree with the five and the pooled result is suspect.
  * `bot`: ZERO everywhere except mfl_12, where the pre-existing
    G6a failure is expected to persist unchanged in kind.
  * `real - shuffle`: POSITIVE and large. Expected to stay
    resolvable; a collapse is the leak signature G6b watches, and
    audible#79 established the signature is SIZE not collapse.

## What a NEGATIVE outcome looks like, stated as concretely as a
## positive one

Any of these is the session's result and is reported as the
headline, not buried:

  1. **Nothing resolves.** All nine `real` comparisons still
     include zero at k=7. Then two extra seasons were not enough
     and the between-season share is what limits this, with a
     measured slope rather than an assumption.
  2. **The probe blocks.** 2019 or 2020 fails on market join
     rate, pool floor, scoring keys, or room coverage. Then the
     session reports UNRESOLVED with the measurement, and pins
     nothing.
  3. **Something un-resolves.** A comparison resolvable at k=5
     stops resolving at k=7. That is evidence the extra seasons
     are a different population, not more of the same, and it
     outranks any newly resolvable result in the report.
  4. **Point estimates move outside their k=5 intervals.** Same
     conclusion as 3, and reported per comparison whether it
     happens or not.
  5. **The room extrapolates badly.** League 6012 has completed
     drafts for five seasons only, so a seven-season run fits the
     room on five and applies it to seven. If that costs
     measurably, k=7 is not comparable to k=5 and the comparison
     is between two harnesses rather than two sample sizes.

## Fixed reporting rule

EVERY comparison is reported at k=5 and k=7 side by side, in
both directions of change, including the ones that got worse and
the ones that never resolved. A session that reports only what
became resolvable has produced nothing, and this file is what
makes that checkable afterwards.

For every comparison the report states whether the k=7 point
estimate falls inside the k=5 interval.

## Fixed in advance: what is NOT allowed to change

  * `replacement.py`, `ordering.py`, any `src/audible/` file.
  * `sim/test_g_b14.py`'s coverage gate, which asserts the
    control variate is anti-conservative. B15 may re-measure the
    estimator at k=7; it may not weaken that gate to adopt it.
  * The seasons themselves. No substitution: a season that does
    not probe clean is reported UNRESOLVED, not swapped.
  * Nothing before 2018. Player counts collapse at 2016-2017.

## Already refuted before this file was written

The handoff states `rec` and `rec_sd` are absent from 2021 and
2023. Measured on the files on disk, `rec` is present in **2024
and 2025 only** and absent from 2018, 2019, 2020, 2021, 2022,
2023 and 2026. `sim/configs/b10-ffc.toml` already recorded this.
It does not block anything: under `historical_deltas` a
reception is worth 0.0 in this league, so an absent reception
count changes no score, and `assert_scoreable` reads the
EFFECTIVE weights rather than a season list.
