# S6 — rebuild the transform

`audible#88` calibrated the referee, so for the first time an accept/reject decision means what
it says. This session fixes the two defects that corrupt everything downstream, inventories every
input the board already carries and discards, and tries transform shapes that are not
`points -> subtract replacement -> sort by VORP`.

Scripts and their committed output live beside this file as `s6_*.py` / `s6-*.out`.

---

## PHASE 1 — the two defects that corrupt everything downstream

### G1 — `score_board.per_position` scored each position over a slice of the GLOBAL pool

`members = [p for p in pool if position.get(p) == pos]`, where `pool = board[:pool_size]`. So
which players a position contributed depended on the **cross-position interleave**, and a term
that provably could not reorder anyone inside a position still moved its per-position score.

The fix takes each position's own top-N **from the full board**, with N derived from the league
config and nothing else — any rule that reads the board under test reintroduces the defect:

    espn_green_hope   pool 128   QB 18  RB 43  WR 43  TE 24
    espn_danger_zone  pool 160   QB 23  RB 53  WR 53  TE 30
    sleeper_boyfun    pool 190   QB 26  RB 55  WR 76  TE 33

Each starting slot contributes `num_teams` of demand, split evenly across the scoreable
positions eligible for it, so a FLEX adds a third each to RB, WR and TE.

**`availability` is the test case**, because it is a within-position constant and therefore
multiplies each position by one positive scalar — it *cannot* reorder anyone inside a position:

    audible#87, global-pool slice   RB +0.159  QB -0.036  WR -0.028  TE +0.0004
    S6, position-local pool         RB +0.000000  QB +0.000000
                                    WR +0.000000  TE +0.000000

Exactly zero at every position in every season. **And it cannot depend on N** — the same term
at half, config and double the pool sizes gives a worst per-position delta of `0.00e+00` in all
three cases. N only sets how deep the question is asked.

**This moves every per-position number in `audible#84` through `#87`.** The floor distribution
is redrawn under the fixed metric before anything in this session is adjudicated, because the
S5 floor's per-position draws were computed under the broken one.

### G2 — `search.py` and `signals.py` built different boards

`_season_inputs` resolved position with `position.update(loaded.position)` in arm order
espn -> ffa -> sleeper, so **the last arm won** and sleeper could overwrite espn. Measured
against espn, which is what `signals.py` reads:

    2019  arms [espn, ffa]            1 disagreement    2022  arms [espn, ffa, sleeper]  3
    2020  arms [espn, ffa]            1                 2024  arms [espn, ffa, sleeper]  3
    2021  arms [espn, ffa, sleeper]   7                 2025  arms [espn, ffa, sleeper]  1
    total 16 across six seasons

    00-0033338  espn RB -> resolved TE      00-0036825  espn QB -> resolved TE
    00-0037304  espn TE -> resolved RB      00-0037745  espn WR -> resolved RB

`setdefault` in the same arm order makes espn authoritative wherever it has the player, and the
other arms fill only what espn has never heard of. After the fix, **0 disagreements and the two
modules build byte-identical boards in all six seasons — asserted in the script.**

### `MIN_SD_REL` retired as the deciding rule

`audible#88` measured that of 217 cells the 20 its tuned threshold skipped **all held exactly
one distinct value**. `distinct <= 1` is a fact about the data rather than a constant anyone
chose, and it now decides; `MIN_SD_REL` is kept only as a second guard.

### Injections

    INJECTION 1  perfect board 0.000000 in all six seasons, and 0.000000 at every position
                 shuffled 42.137 to 57.802
    INJECTION 3  availability through the within-position path FAILS G5 on all four conditions
    INJECTION 4  shrink FAILS G5: moves a within-position ordering in 0/6 seasons
