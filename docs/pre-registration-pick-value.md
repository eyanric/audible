# Pre-registration — the pick-value objective

**Committed before the objective was implemented and before any evaluation number existed.**
Git history is the timestamp. Nothing below is changed after results are seen; a failure to
clear the gate is a reported finding, not a prompt to re-metric.

## Why this question and not the last one

C−B settled the projection question: negative on all three folds, and arm B turned out to be
an inert instrument on top of that. The premise here is different. Seven opponents take the
top standard-scored name off a shared board. Nobody in the room is pricing **scarcity**, the
**recoverability** of a position from the wire, or the **turn**. That is a decision-quality
edge, not a projection edge, and it is testable while holding the projection fixed.

## The quantity

For each candidate at each of my picks:

```
pick_value(c) = points(c)
              - E[ best OTHER player at c.position available at my NEXT pick ]   # delay
              - wire_replacement[c.position]                                     # recoverability
```

- **Delay term.** `E[best other at position]` excludes the candidate himself, because taking
  him now removes him from the pool later. The expectation runs over how many players at that
  position the intervening opponents will take, estimated from **the per-team opponent
  profiles measured over ESPN 6012 2021-2025** (positional picks per round, per manager)
  rather than a position-agnostic survival curve.
- **Turn-aware by construction.** The horizon is *my next pick*, not the next pick. At seat 8
  holding 8 and 9, no opponent picks in between, so the delay term is the gap to the second
  best at that position — which is the whole point of the turn. At pick 9 the horizon is 24
  and fourteen rivals intervene.
- **Wire term.** `wire_replacement` is the **room-behaviour cut**, not the ADP cut: the best
  player at that position left after a realistic 128 picks, where the room spends 8.2 picks on
  kickers and 8.4 on defences. The ADP cut would claim the best kicker alive is free.

Built behind a flag, **OFF by default**. Nothing enters the sort unless the gate below clears.

## The gate

**Success = pick-value drafting beats VORP-order drafting in ≥2 of 3 folds, averaged across
all 8 seats, on actual DDAFFL points, by a margin exceeding between-seat variance.**

Operationally, fixed now:

- Folds `Y ∈ {2023, 2024, 2025}`. Seats `s ∈ 1..8`.
- The seven opponents always draft off **ESPN `standard` rank**, as established.
- My seat drafts twice: once by **VORP order**, once by **pick_value**. Everything else
  identical, including the projection.
- **The projection is held constant across both arms**: prior-season opportunity xFP scored
  through `config.scoring_for(position)`. This is deliberate — the question is decision
  quality on a shared board, so the projection must not be what differs.
- Score each roster on **actual DDAFFL points** for season `Y`, best legal starting nine by
  season totals.
- `d(Y,s) = points_pickvalue(Y,s) − points_vorp(Y,s)` → 24 observations.
- `Δ(Y) = mean over seats`; `SE(Y) = stdev over seats / √8`.
- **Fold win iff `Δ(Y) > SE(Y)`. Gate clears iff ≥2 of 3 folds win.**

Reported alongside, never substituted: all 24 observations, the pooled mean, and **seat 8**
separately from the all-seat average.

## Ablation, also pre-registered

Three variants, same gate, reported together:

| arm | objective |
|---|---|
| **delay only** | `points − E[best other at position at next pick]` |
| **wire only** | `points − wire_replacement[position]` |
| **both** | the full `pick_value` above |

If one term carries the effect, that is the finding and the simpler objective is preferred. A
composite that works for unclear reasons is worse than a single term that works.

**A dimensional concern, stated now rather than discovered later:** the full composite
subtracts two quantities that are not independent — `E[best other at next pick]` is itself
usually at or above `wire_replacement`, so the composite may double-count the baseline and
penalise deep positions twice. The ablation is what will show this, which is why all three
arms are run and reported regardless of which clears.

## Stated asymmetry

The projection driving my seat is prior-season opportunity xFP, which **already measured
worse than ESPN's board** (C2−B was −0.100/−0.092/−0.074 on within-position accuracy). Both
arms carry that handicap equally, so the comparison between them is fair — but it means:

- A **positive** result is strong evidence: a better decision rule overcame a worse projection.
- A **null** is weakly informative: it may reflect the projection's weakness rather than the
  objective's.

## Not being done

- No weight search. No λ. The terms enter with coefficient 1 exactly as written above.
- No metric redefinition after results.
- No promotion without clearing the gate. If it does not clear, the objective stays in the
  **display lane** as a second column beside VORP, and the draft is made on human judgment.
