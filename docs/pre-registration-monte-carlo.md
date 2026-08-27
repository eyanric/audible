# Pre-registration — Monte Carlo roster search (attempt 5 of a declared 5)

**Committed before the search was implemented and before any number existed.**

## The attempt budget, declared

Five distinct approaches have now been tried against **the same five folds**:

| # | approach | result |
|---|---|---|
| 1 | A/B replay — ESPN standard vs reception-re-scored order | **failed**, 0/3 |
| 2 | pick-value objective (delay / wire / composite) | **failed**, 0/3 all arms |
| 3 | redraft, arm S — ADP order + rank-space replacement | **failed**, 1/5 |
| 4 | redraft, arm V — ADP-implied points → real VORP | **failed**, 2/5 |
| 5 | **this**: Monte Carlo roster search over the opponent model | — |

**The significance threshold must be adjusted for that, and is.** Under a null of no edge,
the "≥4 of 5 folds" condition alone has probability

```
P(≥4 of 5 | p = 0.5) = [C(5,4) + C(5,5)] / 2^5 = 6/32 = 0.1875
```

and across five attempts the chance that *at least one* clears it by luck is
`1 − (1 − 0.1875)^5 = 0.65`. **The count condition alone is worth almost nothing here.** An
unadjusted p<0.05 on a fifth attempt corresponds to a family-wise error near 0.23.

So the gate is a **conjunction**, and the quantitative test is Bonferroni-adjusted:

- family-wise target α = 0.05 across 5 attempts → **per-attempt α = 0.05/5 = 0.01**
- the one-sided p-value on the five fold margins (paired bootstrap, 10,000 resamples,
  fixed seed) must be **< 0.01**, reported alongside the gate regardless of outcome.

**If this fails, the conclusion is stated now:** this repo cannot demonstrate a drafting edge
on five seasons, and further attempts are search rather than science. That sentence is
pre-committed so it cannot be softened afterwards.

## The gate

**Both conditions, jointly:**

1. Beats Eric in **≥4 of 5 folds**, and
2. **mean margin > +130 points** (one standard error of the five-fold mean, taken from arm
   V's observed spread).

Reported alongside: the Bonferroni-adjusted p-value above, the room-wide record, and the
standard deviation of season totals against Eric's **166.9**.

## The approach — different in kind

Not another ranking. At each of Eric's picks:

1. Take the top **W = 12** available candidates by the arm-V VORP board.
2. For each, provisionally draft him, then simulate the remainder of the draft **N = 500**
   times. Opponents pick from **their own per-team profile** — positional tendency by round,
   plus a sampled reach drawn from that manager's observed reach distribution.
3. Complete Eric's roster greedily under the same policy used everywhere else (best VORP,
   with the roster-construction slack arithmetic binding in the final rounds).
4. Score each simulated final roster on **ADP-implied points**.
5. Take the candidate with the highest **mean** final roster score.

This optimises the scored quantity directly rather than a proxy, and it is the only arm in
which the opponent model is a **decision input** rather than a description.

## Fixed before running, and not tuned afterwards

| parameter | value | why fixed here |
|---|---|---|
| `N` (simulations per candidate) | **500** primary | the spec's floor |
| `N` room-wide sweep | **200** | eight managers × five folds is 8× the compute; stated in advance rather than discovered as a shortcut |
| `W` (candidate width) | **12** | "top ~15"; 12 keeps the primary run tractable |
| completion policy | greedy arm-V VORP + slack arithmetic | identical to every previous arm, so the *search* is what differs |
| bootstrap | 10,000 resamples, seed 20260827 | deterministic |

**QB, K and DEF stay in the pool with noisy estimates.** The V′ exclusion cost ~450
points/season and that lesson holds.

## Leakage guards, asserted in code

- **LOYO on the ADP→points curve** — `fit_curve` already raises if the fold is in its own
  training years.
- **LOYO on the opponent profiles** — profiles for fold `Y` are built **only** from years
  `≠ Y`. A profile fitted on `Y` would encode how the room actually behaved in the season
  being predicted. This assertion is new and is in the code, not only here.
- Task 1's FFC contamination check still gates: all five windows close before kickoff.

## Also run — the untested league

The best-performing arm repeated under **DDAFFL's actual current scoring** (WR/TE 0.5 a
reception, RB 0.0) instead of standard.

**Labelled a hypothetical, not a replay.** The opponents drafted under standard rules, so
their picks are not what they would have been. It is run because every conclusion so far
describes a league Eric no longer plays in, and that gap is worth measuring rather than
assuming.

## Constraints

No tuning to improve a number. No re-metric. Nothing enters the sort. A loss is reported as
plainly as a win.
