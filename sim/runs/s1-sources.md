# S1 — historical projection source inventory

What exists, what is vintage, and what a ranking loop can actually use as an arm.

Appended per source as each is settled. A finding that lives only in a session's context is
one restart from gone; this file is the durable record.

Every response is pinned under `data/sim-cache/` (gitignored). Nothing fetched is committed.

## The test every source must pass

A projection is useful only if it is the projection **as it stood before that season's draft**.
A number regenerated later, or updated mid-season, encodes hindsight and will look like a
spectacular board.

    T1  next-class absence   season N must not contain N+1's draft class
    T2  magnitude/metadata   full season, or a rest-of-season remainder?
    T3  MAE vs actuals       50-80 is the honest band. Lower means contaminated.
    T4  early-injury case    frozen shows a full season; recomputed has collapsed

T3 is the deciding test. It is the only one that catches a mid-season overwrite of a
full-season projection, which passes both T1 and T2.

---

## espn — CONFIRMED

    endpoint    lm-api-reads.fantasy.espn.com/apis/v3/games/ffl
                /seasons/{YEAR}/segments/0/leaguedefaults/{N}
                ?view=kona_player_info
                header X-Fantasy-Filter with sortDraftRanks
                cookies SWID + espn_s2 (required for history)
    format      45-key raw stat lines (statId -> value), NOT points
    ids         ESPN player id
    seasons     2018-2022, 2024, 2025 usable (seven)
                2023 present but EMPTY -- see below
    pinned      data/sim-cache/espn_probe/leaguedefaults3_{season}.json
                8 files, 103 MB

### the stat sets ESPN actually serves

Per player, `stats[]` carries several kinds. Measured on 2021 (1,119 players):

    seasonId=2021 src=1 split=1   19,515 rows   weekly projection
    seasonId=2021 src=0 split=1   14,292 rows   weekly actual
    seasonId=2021 src=0 split=0    1,119 rows   season actual
    seasonId=2021 src=1 split=2    1,116 rows   (per-game projection)
    seasonId=2021 src=1 split=0    1,063 rows   SEASON PROJECTION <- the one

`statSourceId` 0 = actual, 1 = projected. `statSplitTypeId` 0 = season total. The season
projection is `src=1 split=0`, which is what `_projected_stat_set` in the adapter already
reads.

### coverage — 2023 is the exception and it is not a footnote

Players with a non-zero season projection (`src=1 split=0`):

    season  players  has proj  proj>0  QB>200  RB>150  WR>150
      2018     1042      1005     551      29      32      51
      2019     1111      1064     547      27      34      46
      2020     1092      1044     561      29      35      53
      2021     1119      1062     553      31      33      63
      2022     1136      1098     558      28      38      58
      2023     1132      1128     129       1       3       8
      2024     1097      1064     548      28      36      62
      2025     1089      1051     531      29      37      59

2023 returns the stat set for 1,128 of 1,132 players and then fills almost all of them with
zero. One quarterback projects above 200 points and he is Ryan Tannehill at 211. **ESPN is a
seven-season arm, and a six-season arm for any window spanning 2023.**

### T1 — next-class absence: clean, every season

Oracle is `sim/ffa.py::following_class(season)`, which derives season+1's draft class from the
FFA raw files rather than from memory.

    season  N+1 class size  present in the N pool
      2018             178                      0
      2019              54                      0
      2020              59                      0
      2021              72                      0
      2022             101                      0
      2023              98                      0
      2024              98                      0
      2025              82                      0

### T2 — season-long magnitudes, and they are the right players

Top-5 projected QB, by season, is the check that the pool is preseason consensus rather than
an after-the-fact reordering:

    2018  Brady 313.8, Rodgers 313.3, Newton 299.1
    2019  Mahomes 342.4, Watson 328.9, Ryan 304.7
    2020  Mahomes 341.0, L.Jackson 339.5, Watson 319.4
    2021  J.Allen 377.5, Mahomes 369.4, K.Murray 356.7
    2022  J.Allen 374.6, Mahomes 352.0, Herbert 328.0
    2023  Tannehill 211.4, Hoyer 42.5, Gabbert 19.4   <- empty season
    2024  Hurts 314.3, J.Allen 313.6, Mahomes 307.7
    2025  J.Daniels 371.6, J.Allen 367.9, Hurts 365.5

Full-season magnitudes throughout (~300+ for a QB1), not a remainder.

### T3 — MAE, per season and position

Against ESPN's own season actuals, top-40 by projection at each position:

    season   QB     RB     WR     TE
      2018  68.9   80.1   58.5   52.7
      2019  84.3   59.3   61.3   50.6
      2020  65.9   79.2   63.2   43.1
      2021  68.5   73.1   71.1   44.3
      2022  82.8   65.4   60.5   47.8
      2023 199.3  201.6  218.9  114.4   <- empty season
      2024  65.3   70.9   57.4   44.5
      2025  82.7   68.4   81.1   51.5

Against nflverse PPR points, independent of ESPN entirely:

    season   QB     RB     WR     TE
      2021  72.5   69.8   73.8   42.7
      2024  68.3   73.4   59.3   41.5
      2025  74.6   65.6   78.0   44.2

Inside the 50-80 band, wrong in the ordinary way a preseason number is wrong. Zero exact
matches anywhere.

### the scoring basis — a handoff premise refuted

The handoff states `leaguedefaults/3` is "a default standard-scoring league, matching
espn_green_hope". It is not. Read from ESPN's own `view=mSettings`:

    leaguedefaults/1   "FFL Standard Scoring"       statId 53 ABSENT
    leaguedefaults/2   HTTP 404
    leaguedefaults/3   "FFL PPR Scoring"            statId 53 = 1.0
    leaguedefaults/4   "FFL ESPN+ PPR Scoring"      statId 53 = 1.0

statId 53 is receptions, so its presence is the PPR tell. **`/3` is full PPR; standard is
`/1`.** Scoring a standard league's board under a PPR default is the confound that made
`ffa_vor` unusable in B5.

It is a correction rather than a blocker, because the payload carries **stat lines, not
points**. Christian McCaffrey's 2021 season projection, translated through the adapter's own
`translate_stat_line`:

    rush_yd 1057.73   rush_td 10.01   rec 85.89
    rec_yd   681.33   rec_td   2.59   fum_lost 0.95

45 statIds per row. So one corpus builds a board under any league's rulebook -- Green Hope's
standard, Danger Zone's 1.0/rec, BoyFun's full PPR -- and the `/3`-vs-`/1` question does not
have to be answered by refetching.

The MAE tables above make the same point empirically: scored as standard, WR error runs
97-122; scored as PPR it drops to 59-78, and QB is unchanged either way because quarterbacks
do not catch passes.

### T4 — early-injury cases: frozen

The decisive test. A recomputed projection cannot look like this.

    2020 Saquon Barkley     proj 288.6   actual  15.4   FROZEN (ACL wk2)
    2020 C. McCaffrey       proj 334.9   actual  90.4   FROZEN (3 games)
    2021 C. McCaffrey       proj 334.3   actual 127.5   FROZEN (7 games)
    2021 Saquon Barkley     proj 279.2   actual 148.6   FROZEN
    2024 C. McCaffrey       proj 335.5   actual  47.8   FROZEN (4 games)
    2022 Dalvin Cook        proj 258.5   actual 237.8   control, healthy

The control is what makes the rest mean anything: a player who played a full season projects
close to what he scored, while every player lost early keeps his full preseason number.

### join — 100% per position

`espn_id` -> `gsis_id` through `ff_playerids.parquet` (7,917 crosswalk rows):

    2019  QB 100% (66/66)   RB 100% (131/131)  WR 100% (189/189)  TE 100% (98/98)   K 100%
    2020  QB 100% (68/68)   RB 100% (133/133)  WR 100% (189/189)  TE 100% (107/107) K 100%
    2021  QB 100% (64/64)   RB 100% (131/131)  WR 100% (188/188)  TE 100% (103/103) K 100%
    2022  QB 100% (66/66)   RB 100% (131/131)  WR 100% (187/187)  TE 100% (110/110) K 100%
    2023  QB 100% (5/5)     RB 100% (22/22)    WR 100% (47/47)    TE 100% (28/28)   K 100%
    2024  QB 100% (64/64)   RB 100% (121/121)  WR 100% (187/187)  TE 99.1% (110/111) K 100%
    2025  QB 100% (66/66)   RB 100% (117/117)  WR 100% (186/186)  TE 100% (96/96)   K 100%

Reaching a realised nflverse stat row as well: 96.7-98.3% per season. The residual is players
who were projected and never recorded a snap, which is correct rather than a join failure.

2018 is not joinable today: `player_stats_2018.parquet` is not pinned. The projection is
there; the outcome would need one fetch.

### acquisition cost

Free. Cookie-authenticated, one request per season, already pinned. ESPN restricted historical
access on 2025-08-01, so the `espn_s2` cookie is required and will expire; the pinned files are
what make this reproducible after it does.

---

## injections — all three fired

    1  T1 must be able to FAIL
       2022 pool asked whether it holds the 2022 class:
       72 of 72 present, named (alec pierce WR, breece
       hall RB, ...). Control, same pool vs the 2023
       class: 0 of 101. The test discriminates.

    2  T3 must discriminate
       RB 2021 projection vs actual  MAE = 68.500
       RB 2021 actual vs actual      MAE =  0.000

    3  G3 must be able to collapse
       2021 join, intact crosswalk   100.0% (521/521)
       2021 join, espn_id -> ffc####   0.0% (0/521)

Injection 3 restores the exact historical defect: `weekly.prior_points` once keyed on `ffc####`
against a gsis-keyed roster, every lookup missed, and two sessions of headline numbers were
computed against arbitrary tie-broken lineups.
