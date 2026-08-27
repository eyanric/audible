# Pre-registration — giving Audible a real VORP arm

**Committed before the ADP→points mapping was fitted and before any arm-V number existed.**
Git history is the timestamp.

## Why this addendum exists

FFC returns draft position only. Without projected points there is no VORP, so the previous
redraft quietly demoted Audible to *consensus order plus structure* — and the decomposition
showed exactly what that demotion cost: replacement level expressed in RANK space made QB1
worth `9 − 1 = 8` against WR1's `52 − 1 = 51`, so Audible never took a quarterback until need
forced it and lost **−856 points at the QB slot** across five seasons. Rank distance is not
value distance. This fixes the input rather than accepting the demotion.

## The three arms, reported separately and never pooled

| arm | definition |
|---|---|
| **S** | structure-only: FFC ADP order + replacement level + roster construction. No VORP. This is what already ran. |
| **V** | full VORP: ADP-implied **points** → replacement levels → VORP → Audible's board. |
| **E** | Eric's actual picks. |

**S vs E** and **V vs E** are reported as separate results. They answer different questions
and pooling them would blur the one thing this addendum is testing.

`ff_opportunity` is **not** used for arm V — offense-only, no K/D-ST, no rookies, and it
already measured worse than ESPN's board as arm C. If it appears at all it is labelled a
fourth diagnostic arm, never arm V.

## The ADP → points mapping, fixed now

**Leave-one-year-out is mandatory.** The mapping applied to fold `Y` is fitted **only** on
years `≠ Y`. Fitting on `Y` would leak that season's outcomes into the input and manufacture
a win. Every fold therefore uses a mapping that has never seen its own answers.

**Form, fixed in advance so there is nothing to tune:**

- For each **position** independently, and each **positional ADP rank** `r` (RB1, RB2, …):
  the predicted points is the **mean actual points of the player who held that positional
  rank**, averaged across the training years.
- Smoothed with a **centred 5-rank moving average** (`r−2 … r+2`, truncated at the ends) to
  stop single-season noise at one rank driving a pick.
- Ranks beyond the deepest observed training rank take the last smoothed value.

That is the entire specification. No functional form, no fitted coefficients, no
hyperparameter search. The window is 5 because it is small and odd; it will not be varied.

**Reported for every position:** the fitted curve at representative ranks, the **residual
standard deviation**, and the **Spearman correlation** between predicted and actual on the
held-out fold. A position whose mapping is weak is reported as weak — a noisy input is a
finding about the method, not something to hide.

## The gate — unchanged

**Audible beats Eric's actual roster in ≥4 of the 5 usable seasons.**

**Minimum meaningful margin: 50 actual points**, unchanged and restated. Justified by scale
rather than taste: roughly one starter-quality upgrade sustained across a year — the measured
startable-RB-to-wire gap is ~3.2 points a week, ~54 over a season. A margin below that is not
a draft difference.

Effect size reported in points and as a share of season total. Task 4's all-eight-managers
run is repeated for arm V.

## Task 1 still gates everything

The FFC contamination check has already passed for all five seasons and is re-asserted, not
re-litigated: every sample window closes before that season's first kickoff, Spearman(ADP,
games played) is ≈zero every year, and 2024 ranks Christian McCaffrey at ADP 1.2 in a season
he played four games. Any year that failed would be excluded and not substituted.

## Not being done

- No tuning, no window search, no metric redefinition after results.
- No pooling of S and V.
- Nothing enters the sort on this result without separate review.
