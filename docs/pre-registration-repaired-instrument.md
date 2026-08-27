# Pre-registration — the repaired-instrument rerun (DIAGNOSTIC)

**This is not a gate attempt.** The pre-registered gate has already failed: arm V went 2 of 5
against Eric, mean −81.2, room-wide 12/40. That result stands and is not revisable. Everything
below is a separate, clearly-labelled diagnostic asking *why* it failed, and no outcome here
can clear the original gate.

Committed before the repaired arm was implemented or run.

## Defect 1 — the `teams` parameter is inert

Confirmed directly. `teams=8` and `teams=12` for 2023 return **the same 192 players with the
same ADP for every one**, and identical `meta` (`teams: 12`, `total_drafts: 1104`). The raw
bytes differ by 36 (36,300 vs 36,264) purely in JSON formatting; a same-parameter repeat is
byte-identical. An earlier note in this branch said the payloads were byte-identical — that
was wrong, and the corrected evidence is *semantic* equality.

Every arm therefore ran on 12-team ordering.

### The size adjustment, as a stated formula

League-wide starter demand at position `p` for a league of `T` teams, where `s_p` is starting
slots per team:

```
D_T(p) = T · s_p

A player at positional rank r sits at demand fraction f = r / D_12(p).
His 8-team-equivalent demand rank is

    r' = f · D_8(p) = r · D_8(p)/D_12(p) = r · (8·s_p)/(12·s_p) = r · 8/12
```

**`s_p` cancels.** The ratio is `8/12` for every position:

| pos | s_p | D_12 | D_8 | ratio |
|---|---|---|---|---|
| QB | 1 | 12 | 8 | 0.667 |
| RB | 2 | 24 | 16 | 0.667 |
| WR | 2 | 24 | 16 | 0.667 |
| TE | 1 | 12 | 8 | 0.667 |
| K | 1 | 12 | 8 | 0.667 |
| DEF | 1 | 12 | 8 | 0.667 |

So the adjustment is **uniform** and cannot reprice QB/K/D-ST relative to RB/WR. Applying it
rescales every position by 2/3 and changes no ordering and no VORP. The premise that 12-team
ADP over-prices QB/K/DEF *by the starter-count ratio* does not hold — the ratio is the same
everywhere.

Arm V's replacement levels already come from the 8-team config, so its VORP is already an
8-team VORP. The genuine 12-team residue is **which players are in the FFC pool at all**, and
no formula recovers that.

## Defect 2 — the exclusion rule, and the list it produces

**Rule, fixed now:** a position enters VORP only if its mean held-out Spearman exceeds the
noise floor for that position's sample size:

```
include p  iff  mean_rho(p) > 1 / sqrt(n_p - 1)
```

A formula rather than a chosen number. Positions that fail are **excluded from VORP and
drafted by roster need in the final rounds**.

**This is a repaired instrument, not an out-of-sample test.** We already know which positions
it catches, because the fit was published before the rule was written. Stated openly so the
result is read for what it is.

Applying it to the already-published fit:

| pos | mean held-out ρ | typical n | noise floor | verdict |
|---|---|---|---|---|
| RB | 0.547 | 60 | 0.130 | **include** |
| WR | 0.464 | 68 | 0.122 | **include** |
| TE | 0.253 | 20 | 0.229 | **include** (marginal) |
| QB | 0.187 | 25 | 0.204 | **EXCLUDE** (marginal) |
| DEF | 0.103 | 13 | 0.289 | **EXCLUDE** |
| K | −0.017 | 14 | 0.277 | **EXCLUDE** |

**Excluded from VORP in arm V′: QB, K, DEF.**

### A prediction, stated before running

Excluding QB should make arm V′ **worse at quarterback than arm V**, because it reverts QB to
need-based late drafting — which is precisely what arm S did, and arm S lost −856 at the QB
slot. If V′ improves overall it will be despite QB, not because of it. Recorded now so the
result is interpretable in either direction.

## What is run

Arms **S**, **V**, and **V′**, same five folds, same LOYO assertion in code, same
contamination check. All three reported against Eric and room-wide, never pooled.

## Also reported

- Per-year slot decomposition for 2022 (−469.7) and 2021 (−250.3): spread or a few picks?
- Standard deviation of season totals per arm, against Eric's. A higher-variance strategy
  with a lower mean is worse on both axes and should be said so.

## Constraints

No tuning to improve a number. No re-metric. Nothing enters the sort.
