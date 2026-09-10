# S5 — fix the referee, then re-adjudicate everything it decided

`audible#87` established that the noise floor is a distribution, not a number, and that its own
variance is larger than most effects this project has measured. Every accept/reject decision in
`audible#86` and `#87` was made against a single draw of it. This session fixes the mechanism
and re-decides what the broken mechanism decided.

Scripts behind every number here, all committed (G10):
`sim/referee.py`, `sim/runs/s5_floor.py`, `sim/runs/s5_gate.py`, `sim/runs/s5_adjudicate.py`.
The floor's 24 draws are frozen in `sim/runs/s5-floor.json` so every adjudication in this
session reads the same numbers.

---

## TASK 2 — G5 rebuilt, and what it now rejects

The old gate asked one question — "did some ordering move" — through a **different code path**
than the one that decided whether the term applied. That is how `availability` passed on 214
players displaced by 8.95e-16 of floating-point residue.

Three conditions now hold together, and each exists because a specific term slipped through:

    1. the term APPLIES in at least two seasons          availability was live in one
    2. every applied cell clears MIN_SD_REL = 1e-9       that one cell was float residue
    3. the board ordering MOVES in at least two seasons  shrink was said to move none

Condition 2 is enforced inside `signals.cells`, **which `adjust` itself calls**. The gate and
the transform cannot diverge again without that one function changing under both.

### INJECTION 2 — the float-residue term FAILS, as required

`availability` unchanged from `audible#87`, through the within-position path:

    availability (scope=position): FAILS
      applies in 0/6 seasons
      cells applied/skipped: 0/24
      players displaced by season: 2019:0 2020:0 2021:0 2022:0 2024:0 2025:0
      REASON: applies in 0 season(s), needs 2
      REASON: no cell clears the minimum standard deviation
      REASON: moves an ordering in 0 season(s), needs 2

Every one of the 24 cells is skipped, including the 2022 quarterback cell that `audible#87`
applied: `sd = 8.950e-16 <= 7.974e-09`. **The published +0.071 cannot be produced any more.**

A detail the old run never surfaced: `availability` has **no value at all in 2019** — n=0 in all
four cells, because the rate is built from seasons strictly before season−1 and
`player_stats_2018` is the earliest file. It was a five-season term reported as a six-season one.

### INJECTION 3 — FAILED AS WRITTEN, and the premise is refuted

`audible#85`, `sim/signals.py`'s own docstring, and this handoff all assert that `shrink` is
**provably inert**: "uniform scaling of VORP leaves the order unchanged, and the board was
byte-identical at s=0.0 and s=0.4".

**It is not.** Measured at s=0.40, per season:

    2019  displaced   0   board identical: True
    2020  displaced 377   board identical: False
    2021  displaced   0   board identical: True
    2022  displaced   0   board identical: True
    2024  displaced 353   board identical: False
    2025  displaced   0   board identical: True

The algebra is right as far as it goes — within a position, a player and his own replacement
contract by the same factor, so VORP scales by (1−s) and no pair can cross. It assumes the
**replacement rank is stable**, and in two seasons it is not. `compute_vorp` assigns FLEX slots
by simulating every team filling its lineup from the projection-ranked pool, so compressing
each position toward its own mean changes **who wins the flex**:

    2020  RB starters 23->24   rostered 50->52   replacement rank 51->53
          WR starters 17->16   rostered 37->35   replacement rank 38->36
    2024  RB starters 23->24   rostered 50->52   replacement rank 51->53
          WR starters 17->16   rostered 37->35   replacement rank 38->36
    2021  every position unchanged  -> the board IS byte-identical

One flex slot moves from wide receiver to running back, both replacement levels move two ranks,
and the uniform-scale property breaks. Confirmed on the VORP ratios directly: in 2021 every one
of 479 players has `new/base = 0.600000` exactly, one distinct ratio; in 2020 there are **318**
distinct ratios spanning −1.03 to +3.99.

**Consequences, and they are larger than this injection:**

1. **G4 as written cannot be satisfied.** `shrink` moves an ordering in exactly two seasons,
   which meets condition 3. The rebuilt gate **passes** it. Tuning the threshold to three
   seasons purely to force the demanded verdict is the exact failure this session exists to
   fix, so it was not done. **G4: FAILS — reported, not engineered away.**
2. **`shrink` was never inert and should have been measured.** `audible#85` rejected it on a
   false premise.
3. **The replacement level is not stable under a monotone within-position rescaling.** Any
   transform that changes the *shape* of a position's distribution can silently move the
   cross-position interleave through the flex allocation, without moving a single player
   within his own position. That is a property of the transform the rebuild will inherit.

### G4/G5 — the terms this session measures

    availability (board)   PASSES  5/5 seasons  cells 5/0    min sd 5.795e-01
    snap_share             PASSES  6/6 seasons  cells 24/0   min sd 2.020e-01
    adp_gap                PASSES  6/6 seasons  cells 24/0   min sd 3.218e+00
    draft_round (rookies)  PASSES  6/6 seasons  cells 21/3   min sd 1.098e+00
    ngs_separation         PASSES  6/6 seasons  cells 12/12  min sd 3.981e-01
    ngs_rush_eff           PASSES  6/6 seasons  cells  6/18  min sd 3.411e-01
    ngs_time_to_throw      PASSES  6/6 seasons  cells  6/18  min sd 1.133e-01
    contract               PASSES  6/6 seasons  cells 24/0   min sd 1.432e-02
    noise                  PASSES  6/6 seasons  cells 24/0   min sd 5.160e-01

The skipped counts are the positional signals declining to act outside their own locus, which
is correct: `ngs_rush_eff` applies in 6 of 24 cells because it is charted for ball carriers.

### G5 — `availability` actually applies now

    scope=position  0 of 496 point values changed   (all 24 cells skipped)
    scope=board   496 of 496 changed, sd 5.795e-01, 4 distinct values

A position-level constant has zero spread *within* a position, so the within-position path
could only ever skip it or fire on rounding residue. `board` scope standardises across the pool,
which is the only route by which such a term can move the cross-position interleave — the locus
`audible#87` correctly predicted and never tested.

### INJECTION 5 — the perfect board and the shuffled board

    2019  perfect 0.000000   shuffled 53.038
    2020  perfect 0.000000   shuffled 52.123
    2021  perfect 0.000000   shuffled 42.137
    2022  perfect 0.000000   shuffled 55.229
    2024  perfect 0.000000   shuffled 53.487
    2025  perfect 0.000000   shuffled 57.802

Exact zeros, and chance is 42–58 RWRE. The metric is calibrated.

---

## TASK 4 — can the window be extended? NO, and the board is the reason

The handoff asks whether Next Gen Stats coverage back to 2016 adds seasons for
`ngs_separation`, since more seasons is the only thing that raises the LOSO's degrees of
freedom. It does not, and the binding constraint is **not** the signal:

    2016  board FAIL: espn 2016 is excluded and is not substituted
          realised FAIL: realised outcomes missing for 2016
    2017  board FAIL / realised FAIL
    2018  board FAIL / realised FAIL
    2019  board 481   realised 572   ngs_separation 125
    2023  board FAIL: espn 2023 is excluded    realised 577

ESPN is a **seven-season** vintage source beginning 2019 (`audible#83`), and realised outcomes
are pinned 2019–2025 only. Extending the NGS window would add a signal for seasons that have no
board and no truth to score it against. **Six seasons is the maximum, 2023 is permanently
missing, and the LOSO has six folds and cannot have more.** This is a hard ceiling on the
degrees of freedom available to every result in this project, and it is set by the board source.
