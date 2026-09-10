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

**`availability` reading +0.000000 is a CONSISTENCY CHECK, NOT EVIDENCE.** The review caught
this and it is worth stating plainly: under the new rule the per-position member list is the
position's own top-N, and `availability` scales each position by a single positive scalar, which
is order-preserving. So the member list is byte-identical before and after and the metric
compares `x` with `x`. It is true by construction — `sim/signals.py::position_availability` says
so in its own docstring — and the half/config/double sweep is the same identity evaluated three
times.

    audible#87, global-pool slice   RB +0.159  QB -0.036  WR -0.028  TE +0.0004
    S6, position-local pool         exactly +0.000000 at all four, in all five seasons

(Five, not six: `availability` is built from seasons strictly before season−1 and
`player_stats_2018` is not pinned, so 2019 has no value at all. The old figures were also
concentrated rather than uniform — RB was non-zero in three of the five seasons and QB and WR in
one each.)

**The real evidence is a leakage test.** A per-player pseudo-random term applied to **RB only**:
under `scope=position` the QB, WR and TE cells hold no values at all, so those three positions
are untouched by construction and *must* read exactly zero. RB must move. This is falsifiable,
and the old rule fails it:

    season   NEW rule                                OLD rule
    2019     QB/WR/TE +0.000000  RB +0.893           TE -1.236, WR -0.071
    2020     QB/WR/TE +0.000000  RB +2.926           WR -1.056, QB -0.178, TE +0.392
    2021     QB/WR/TE +0.000000  RB +1.409           no leak
    2022     QB/WR/TE +0.000000  RB +3.432           WR -0.541, TE +0.044
    2024     QB/WR/TE +0.000000  RB +2.459           no leak
    2025     QB/WR/TE +0.000000  RB +4.325           TE -0.024

    worst leak into an untouched position:  NEW 0.00e+00   OLD 1.236
    seasons where the old rule leaked: 4 of 6

**An RB-only term moved tight end by 1.236 RWRE** — larger than any signal effect this project
has measured. That is what the fix removes.

**N is a pre-registered free parameter, and it is not innocuous.** `position_pool_sizes` gives
green_hope QB 18, but a 1-QB 8-team league only ever drafts about ten quarterbacks — QB#18 sits
at global board rank 158–262 against a 128-pick draft, so **half the QB metric is players nobody
drafts**. For an inert term N genuinely does not matter; for a term that carries information it
can decide the sign. Measured on `ngs_time_to_throw` at QB:

    2019  N=9 +0.811   N=18 -0.643   N=36 -2.032
    2021  N=9 -0.340   N=18 +1.790   N=36 +0.389
    2022  N=9 -1.477   N=18 -0.587   N=36 -0.294
    2025  N=9 +0.000   N=18 -1.063   N=36 +0.419

Sign flips in three of six seasons. **Every per-position conclusion in this session is therefore
reported across N**, and one that does not survive the sweep is not reported as a result.

**`position_pool` is required, not defaulted.** A fallback would have been a *third* rule —
neither the global slice nor the config-derived N — reachable by any caller that forgot the
argument. `score_board` now raises instead, and the three historical scripts that called it
without one were updated.

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

**espn-first is *a* resolution, not provably *the* one.** The justification "match what
`signals.py` reads" is circular; it makes search agree with signals by declaring signals correct.
There is a real architectural inconsistency underneath: **the realised side already buckets by
nflverse** — `realised_per_game` takes position from `player_stats_*.parquet` — so replacement
levels are computed in nflverse's buckets while the board is built in espn's. Measured: 20
espn-vs-nflverse disagreements across the six scored boards, and **0 inside the per-position
member lists**. So it has no measurable effect today and is recorded as a known inconsistency
rather than fixed here.

### `MIN_SD_REL` retired as the deciding rule

`audible#88` measured that of 217 cells the 20 its tuned threshold skipped **all held exactly
one distinct value**. A wider census over 389 cells confirms it: 20 skipped by both rules, **zero
cells where the threshold still decides, and zero where `distinct` is stricter**. The nearest
live cell sits 672,000x above the threshold.

**This change is behaviourally a no-op and should be described as one** — the code tests
`distinct <= 1` first and *then* still tests the floor, so the rule is the union and the skip set
is provably unchanged. What it buys is that the deciding condition is now a fact about the data
rather than a constant someone chose.


### Injections

    INJECTION 1  perfect board 0.000000 in all six seasons, and 0.000000 at every position
                 shuffled 42.137 to 57.802
    INJECTION 3  availability through the within-position path FAILS G5 on all four conditions
    INJECTION 4  shrink FAILS G5: moves a within-position ordering in 0/6 seasons
