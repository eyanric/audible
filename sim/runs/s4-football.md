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
