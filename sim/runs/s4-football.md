# S4 — the football data we never fetched

Every signal Step 2 tested came from fantasy projections: models built by different people from
the same box scores. This session tests physical measurement, human charting, injury
designations and contract value instead. All free, all permanent.

Appended as each result lands.

---

## TASK 1 — what `nflreadpy` actually serves, verified

All pinned under the gitignored `data/sim-cache/nflverse/*_s4.parquet`.

**A loader default that matters and is easy to miss:** `seasons=None` means CURRENT SEASON ONLY,
not "everything". The first Next Gen Stats pull returned 605 rows for 2025 alone and looked like
a coverage limit; it was an argument default. `seasons=True` or an explicit list gets the
history. Anyone reading a one-season result off these loaders should check this first.

    source          seasons        rows      id space          join
    nextgen_pass    2018-2025 (8)   4,785    player_gsis_id    100.0%  (65 ids)
    nextgen_rec     2018-2025 (8)  11,708    player_gsis_id    100.0%  (212 ids)
    nextgen_rush    2018-2025 (8)   4,885    player_gsis_id    100.0%  (81 ids)
    injuries        2018-2025 (8)  45,337    gsis_id            82.4%  (3219/3905)
    contracts       all-time       52,751    gsis_id            60.7%  (6723/11075)
    ftn_charting    2022-2025 (4) 185,215    NONE -- play level    n/a
    participation   2018-2025     382,557    packed list        see below
    officials       2015-2026 (12) 22,012    game level, no players

### the three that are ready to use

**Next Gen Stats — physical measurement, and it joins perfectly.** `week = 0` rows are season
aggregates, which is exactly the shape a prior-season signal needs. The columns are what the
premise promised:

    passing    avg_time_to_throw, aggressiveness,
               avg_air_yards_differential, avg_air_yards_to_sticks
    receiving  avg_separation, avg_cushion, avg_yac,
               percent_share_of_intended_air_yards
    rushing    efficiency, avg_time_to_los,
               percent_attempts_gte_eight_defenders

100% join on `player_gsis_id` for all three. The row counts are small because these are
season-and-week aggregates over qualifying players, not play-level data.

**Injuries — the availability signal, and it has more than designations.** Per player-week:

    report_status     Questionable, Out, Doubtful, Note
    practice_status   Full / Limited / Did Not Participate
    report_primary_injury, practice_primary_injury (body part)

82.4% join. 2018-2025. This is 3a and it is the highest-priority signal by
`audible#83`'s measurement -- prorating projections by games actually played collapsed MAE from
53-63 to 34-43.

**Contracts — available, 60.7% join.** All-time from OTC. The join rate is the weakest of the
three and reflects that OTC carries players nflverse never assigned a gsis id.

### the two that are NOT player-keyed as delivered

**FTN charting carries no player identifier at all.** Every one of its 29 columns is a PLAY
attribute -- `is_play_action`, `n_blitzers`, `is_drop`, `is_contested_ball`,
`is_interception_worthy`. Keys are `nflverse_game_id` and `nflverse_play_id`. Turning it into a
player signal requires joining play ids to play-by-play and attributing each play to its
participants, which is a real build rather than a fetch. The handoff says FTN is "thin"; it is
thinner than that -- it is **not player-keyed**, so 3c is not a one-iteration job and was not
attempted. **UNRESOLVED, with the cost stated.**

**Participation IS player-attributable, but only after unpacking.** `offense_players` is a
semicolon-delimited gsis list, non-empty on 361,514 of 382,557 plays, and `route` is populated
on 228,273. So route participation -- the signal S3's usage list wanted and could not get -- is
derivable. But it means exploding 361k plays across ~11 players each, and there is no `season`
column (the year has to come off the game id). Also not a one-iteration job.

**Officials is game-level with no player ids.** Irrelevant to a player ranking. Not pursued.

### nfl_data_py — NOT pursued, and the reason is the session's own rule

It is not installed. `CLAUDE.md` records that it is **archived upstream** and that `nflreadpy`
is the replacement. Adding an archived dependency to reach one scrape fails the sustainability
requirement this handoff itself sets out ("a source that must be re-purchased every season
fails" -- an abandoned library is the same problem with a different clock). **UNRESOLVED by
choice, not by failure.**

---

## G5 — every new term moves an ordering, demonstrated before measurement

    ngs_time_to_throw  413 players displaced from the 2022 board
    ngs_separation     356
    ngs_rush_eff       282
    availability       214

`audible#85`'s `shrink` displaced zero. All four of these can change a board.

## THE NOISE FLOOR, rotated leave-one-season-out

    board-wide: +0.364

**But see the locus finding below -- this number turned out to be the wrong floor for three of
the four signals tested, and using it would have produced a false positive.**

---

## TASK 3 — the signals, each tested WHERE IT ACTS

### 3a. availability (position-level) — REVERTED, and inert exactly as predicted

Expected locus, stated before running: **the cross-position interleave ONLY.** A value constant
within a position cannot reorder that position, so its per-position error is inert by
construction and only the interleave can move.

    board-wide mean delta  +0.071
    per-position  QB +0.000  RB +0.000  WR +0.000  TE +0.000

**The prediction is confirmed to the digit: all four positions read exactly +0.000.** The
structural claim was right, and the board-wide movement is +0.071 -- nominally worse, and
essentially nothing.

Measured position rates (mean games played, prior seasons): RB 9.48, WR 9.80, TE 8.99, QB 7.97.
These include every player with a row, so backups drag them down; they are a position's average
availability, not a drafted player's. **REVERTED.**

### 3b. Next Gen Stats — one resolved result, then the control killed it

    signal              locus    focus delta   board-wide   dilution
    ngs_separation      WR,TE          -0.337       -0.436     -0.100
    ngs_rush_eff        RB             +0.087       +0.017     +0.070
    ngs_time_to_throw   QB             +0.669       +0.038     +0.630

**INJECTION 4 FIRES, and `ngs_time_to_throw` is the clean demonstration.** A quarterback-only
signal reads +0.669 at quarterback and +0.038 board-wide -- a **seventeen-fold attenuation**.
Averaging a positional effect across four positions does not merely weaken it, it erases it.
Note the direction: here the dilution hid a HARM, not a benefit. It hides both.

Paired per-player, at each signal's own position:

    ngs_separation     WR  -0.683 [-1.140, -0.213]  n=242  RESOLVED
    ngs_separation     TE  +0.181 [-0.109, +0.457]  n=128  not resolved
    ngs_time_to_throw  QB  -0.005 [-0.495, +0.472]  n= 52  not resolved
    ngs_rush_eff       RB  +0.139 [-0.104, +0.373]  n=319  not resolved

**Receiver separation at wide receiver is the first resolved improvement this project has
produced** -- across `audible#84`, `#85`, `#86` and everything above, no signal had ever
excluded zero. It is WR-specific, as the mechanism requires: the same signal at tight end is
+0.181 and not resolved.

### and then the correct control refuted it

The board-wide floor is +0.364. **At wide receiver specifically the floor is -0.296**, because
the noise knob tuned on a single position's slice behaves differently from the same knob tuned
board-wide.

    noise at WR:  -0.296 [-0.789, +0.204]

So the honest comparison is separation against noise **at the same locus, at the same lambda**:

    separation - noise at WR:  -0.267 [-0.843, +0.301]  n=227  NOT RESOLVED

And it does not survive dropping a season:

    all six seasons          -0.683 [-1.140, -0.213]  RESOLVED
    excluding 2021          -0.495 [-0.992, +0.013]  not resolved
    excluding 2025          -0.582 [-1.103, -0.059]  RESOLVED
    excluding 2021 and 2025 -0.324 [-0.921, +0.250]  not resolved

    per season: 2019 -0.713  2020 -0.081  2021 -1.673
                2022 -0.435  2024 +0.690  2025 -2.086

**DISPOSITION: REVERTED.** It beats the untreated baseline and fails against the only control
that matters.

---

## THE METHODOLOGICAL FINDING — a floor must be measured at the signal's own locus

This is the session's most transferable result, and it is a correction to G3 as written.

G3 says "report the noise floor beside every signal". G4 says "test each signal where it should
act". **Taken together and applied naively they produce a false positive**, which is exactly
what happened here: comparing a WR-locus signal (-0.683) against a board-wide floor (+0.364)
makes it look decisively good. Against the WR-locus floor (-0.296) it is not resolved.

The floor is not a property of the harness. It is a property of the harness AND the slice. A
knob tuned on 242 receiver-observations has more room to fit than the same knob tuned on 751
board-wide observations, so the floor moves -- and it moved by 0.66 RWRE here, which is larger
than the effect being tested.

**Any future session testing a positional signal must measure the floor at that position.**
Reporting the board-wide floor beside a positional result is not a control; it is a
mismatched comparison that flatters every positional signal.

### 3d. contract value — REVERTED, and the handoff's collinearity worry is refuted

`apy_cap_pct` of the most recent contract signed **strictly before** the season -- annual value
as a share of that year's cap, so the doubling of the cap across the window does not leak the
calendar into the signal. Coverage 7,860 players, G5 displaces 451.

**The collinearity concern is refuted by measurement.** The handoff says contract value is
"likely correlated with draft capital; check for collinearity before claiming anything adds".
Measured: `corr(apy_cap_pct, draft_round) = -0.371` over 3,637 players. Related, as one would
expect, and nowhere near collinear.

    position  lambda   vs baseline                    vs NOISE at that position
    QB         +0.00   +0.000                          +0.000
    RB         +0.05   -0.018 [-0.347, +0.325] ns     -0.426 [-0.823, -0.030] RESOLVED
    WR         +0.00   +0.000                          +0.000
    TE         +0.10   +0.106 [-0.339, +0.574] ns     +0.884 [+0.181, +1.615] RESOLVED WORSE

Five of six folds chose lambda = 0 at quarterback and half did at receiver -- the fit declines
the signal outright at two positions. At running back it beats noise but not the untreated
baseline, which is not a signal: "less harmful than a hash" is true of any adjustment near zero.
At tight end the fitted lambda flips sign across folds (+0.1, +0.1, -0.1, -0.1, -0.1, +0.1) and
it is resolvably WORSE than noise.

**DISPOSITION: REVERTED.**

---

## THE FLOOR IS POSITIONAL, AND IT VARIES BY MORE THAN ANY SIGNAL MEASURED

Measuring the noise floor at each position separately -- which the false positive above forced
-- produced the session's most transferable result:

    board-wide floor   +0.364
    QB                  +0.000  (the fit declines noise entirely)
    RB                  +0.412  [+0.131, +0.679]  RESOLVED -- noise HURTS
    WR                  -0.296  [-0.789, +0.204]  ns
    TE                  -0.701  [-1.301, -0.138]  RESOLVED -- noise HELPS

**At tight end, adding a sha256 of player and season improves the board by 0.7 RWRE, and the
interval excludes zero.** That is not a bug in the hash; it is a statement about the slice. TE
carries 124 paired observations against RB's 315, and a board that is poorly calibrated on a
small, noisy position can be improved by almost any perturbation that breaks its ordering.

The floor therefore ranges over **1.11 RWRE across positions** -- wider than every signal effect
this session measured, and wider than the separation result that looked resolved.

**Consequences, stated for whoever runs the next one:**

1. **G3 as written is not sufficient.** "Report the noise floor beside every signal" produces a
   mismatched comparison the moment G4's "test where it acts" is also obeyed. The floor must be
   measured at the same locus, the same lambda and the same n.
2. **A positional result compared to a board-wide floor is uninterpretable.** Separation at WR
   read -0.683 against a board-wide +0.364 and looked decisive; against the WR floor of -0.296
   it is not resolved.
3. **A negative floor is a diagnostic in its own right.** TE's -0.701 says the board's tight-end
   ordering is worse than its own noise, which is a finding about the board rather than about
   any signal, and nothing in this project had measured it before.
