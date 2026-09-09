# S2b — search the space, don't check a list

`audible#84` built a validated harness and then ran four hand-written hypotheses. This session
fixes the metric's known blindness, then searches the space instead of checking a list.

Appended as each result lands.

---

## TASK 2.0 — the metric was blind to half the board, and now is not

`audible#84`'s own adversarial review measured the primary metric as **4.4x asymmetric**. The
weight was indexed by BOARD rank -- the pick you spend -- so the metric priced "do not draft a
bust early" and was nearly blind to "find a sleeper". A source or signal could differ
substantially at late-round value and that metric structurally could not see it.

### three indexings

    board       w = 1/round(board_rank)      audible#84's
    realised    w = 1/round(realised_rank)   the mirror
    symmetric   w = max(board_w, realised_w) prices both

`symmetric` takes the LARGER of the two: an error is costly if EITHER the pick was expensive OR
the player was valuable. It is the only one of the three that can see both failure modes.

### the asymmetry, measured under each (green_hope 2021)

    indexing    bury-the-best   promote-the-worst   asymmetry
    board                1.29                5.66       4.38x
    realised             5.66                1.29       0.23x
    symmetric            5.50                5.50       1.00x

`realised` is not a fix -- it is the same blindness pointed the other way, and it would have
made "roster a bust" nearly free. **`symmetric` is exactly balanced at 1.00x.**

### G1 holds under all three, in all three leagues

    league          board                realised             symmetric
    green_hope      0.000000 / 48.35     0.000000 / 48.40     0.000000 / 53.46
    danger_zone     0.000000 / 60.23     0.000000 / 60.27     0.000000 / 66.62
    boyfun          0.000000 / 72.25     0.000000 / 72.26     0.000000 / 79.78

(perfect board / shuffled mean). Symmetric's chance level is higher because `max` produces
larger weights; the perfect board is still exactly zero, which is what G1 asserts.

---

## G2 — every audible#84 headline, re-reported under the new indexings

### the source equivalence SURVIVES, and that is the important one

`ffa - espn`, paired over players, out-of-sample 2024-2025:

    league        board                    realised                 symmetric
    green_hope    +0.22 [-0.68,+1.12] ns   +0.58 [-0.57,+1.81] ns   +0.30 [-0.76,+1.42] ns
    danger_zone   -0.02 [-1.09,+0.97] ns   -0.24 [-1.76,+1.24] ns   -0.05 [-1.33,+1.20] ns
    boyfun        +0.32 [-0.58,+1.20] ns   +0.47 [-0.88,+1.82] ns   +0.48 [-0.68,+1.62] ns

**Not resolved under any indexing, in any league.** The bounded equivalence audible#84 reported
was not an artifact of the asymmetric weighting. No source "pulls ahead under realised-rank
weighting", which was the specific thing the handoff asked this task to look for.

### sleeper's boyfun win SURVIVES and GROWS

`espn - sleeper` in boyfun:

    board      +2.86 [+1.07, +4.62]  RESOLVED
    realised   +4.04 [+1.35, +6.69]  RESOLVED
    symmetric  +3.69 [+1.41, +5.94]  RESOLVED

Resolved under all three, and larger under the indexings that price sleepers. Sleeper's
advantage in boyfun is partly an advantage at players the old metric under-weighted.

### one thing the new indexing does change

Absolute levels move, and the NOMINAL green_hope leader flips:

    green_hope   board      ffa 20.27  espn 20.33  sleeper 21.52  ecr 30.27
                 realised   espn 19.34  ffa 19.96  sleeper 20.10  ecr 28.27
                 symmetric  espn 22.75  ffa 22.94  sleeper 23.71  ecr 32.18

Under `board` ffa is nominally first by 0.06; under `realised` and `symmetric` espn is
nominally first by 0.6 and 0.2. All of it is inside the interval, so nothing is resolved and no
claim changes -- but it is worth stating that the nominal ordering was never stable and reading
it as a ranking was always over-reading.

`ecr` remains resolvably worst under every indexing.

### danger_zone moves toward resolving but does not

`espn - sleeper` in danger_zone goes +1.42 ns (board), +2.54 [-0.19, +5.30] ns (realised),
+2.05 ns (symmetric). Under `realised` the interval nearly excludes zero. Recorded as a
near-miss rather than a result.
