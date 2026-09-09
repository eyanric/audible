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

---

## sleeper — CONFIRMED 2021-2025, REFUTED 2018-2020

    endpoint    https://api.sleeper.com/projections/nfl/{season}
                ?season_type=regular&position[]={pos}
                &order_by=pts_half_ppr
                (src/audible/adapters/sleeper.py:162, BASE_COM
                 line 33 -- CLAUDE.md's app-vs-com split confirmed)
    auth        none. No key, no cookie, no rate limit hit.
    format      granular stat lines + pts_std/pts_ppr/pts_half_ppr
                + 12 adp_* market fields
    ids         sleeper_id
    seasons     HTTP 200 for 2017-2025 x 9 positions, but only
                2021-2025 are VINTAGE. See below.
    pinned      data/sim-cache/sleeper_probe/ (63 files, ~50 MB)

### 2019 and 2020 are contaminated, and `gp` is what gives it away

The decisive measurement. In a frozen preseason projection every player is projected for a
full slate; in a recomputed one the games-played field knows how the season went.

    season  top-100 where gp == actual games   mean(gp - actual)
      2019                     67 (67.0%)                 -0.34
      2020                     86 (86.0%)                 -0.09
      2022                      0 ( 0.0%)                 +3.57
      2025                      0 ( 0.0%)                 +4.10

2021 onward `gp` is FLAT -- 17.0 for every player in 2021, 18.0 for every player in 2024.
2019 varies: gp_top = [(16, 80), (15, 74), (14, 48), (12, 33)]. 2020 Saquon Barkley, who tore
his ACL in week 2, carries `gp=2.0, pts=35.12`. That is not a projection.

T3 agrees independently. 2019/2020 land at MAE 13-49 with correlation ~0.90, which no
preseason forecast achieves. 2021-2025 land at 29-79 with a large positive bias -- the exact
signature of a full-slate forecast meeting real attrition.

    2019 WR  MAE 20.7  r 0.836      2022 WR  MAE 37.0  r 0.721
    2020 RB  MAE 19.7  r 0.921      2024 RB  MAE 51.8  r 0.634
    2020 TE  MAE 16.5  r 0.905      2025 QB  MAE 79.1  r 0.094

### T1, T2, T4 on the good seasons

T1 -- next-class absence PASSES, with a subtlety worth recording. The row SKELETON is today's
catalog, so next-class players appear; but they carry a bare `{"gp": 17.0}` stub with no
numbers. Breece Hall, Garrett Wilson and Chris Olave in the 2021 file are stubs.

    2021: class(2022)=72   rows present 71   WITH STATS 0
    2023: class(2024)=98   rows present 98   WITH STATS 0
    2025: class(2026)=82   rows present 81   WITH STATS 0

T2 -- full season. 2026 QB1 Josh Allen 361.5 half-PPR at gp=18.
T4 -- frozen. 2021 CMC projected 319.3 against an actual 109.0 in 7 games, +210.3.
2024 CMC 250.4 vs 40.3, +210.1. 2024 Pacheco 215.4 vs 50.9.

### the one real leak in the good years: survivorship blanking

Players with a real projection in both S-1 and S+1, but a blanked stub in S:

    S      cohort  real   stub | mean actual games: real   stub
    2022      388    371     17 |                  11.18   2.24
    2023      383    367     16 |                  11.58   2.12
    2024      355    344     11 |                  12.13   2.64

The stubbed players played about two games. The 2023 roll-call is Aaron Rodgers (1 game),
Nick Chubb (2), J.K. Dobbins (1). Their projection is blanked -- **but the vintage ADP
survives** (Chubb 2023 `adp_half_ppr=10.6`, correct for that year). At draft-relevant depth
this is 0-3 names a season, every one a season-ender:

    S     adp_idp<=200   no projection   mean actual games (missing)
    2021           198        2 (1.0%)                         0.00
    2023           196        3 (1.5%)                         1.33
    2025           205        0 (0.0%)                          n/a

Small, but it is exactly the worst-outcome tail, and a 2023 replay would silently never offer
Chubb at ADP 17. It is DETECTABLE (ADP present, projection absent) and therefore patchable --
but a backtest that does not handle it inherits a survivorship look-ahead.

### IDP — the unique value, and the reason this arm matters

Granular IDP returns for 2020 onward. Keys: `idp_tkl_solo, idp_tkl_ast, idp_tkl, idp_sack,
idp_int, idp_ff, idp_fum_rec, idp_safe, idp_blk_kick`.

    2021  DL 229 / LB 250 / DB 287      2024  DL 498 / LB 384 / DB 563
    2022  DL 295 / LB 250 / DB 339      2025  DL 519 / LB 367 / DB 523
    2023  DL 165 / LB 154 / DB 187   <- thin

Note `pts_*` are NOT IDP-scored (T.J. Watt 2026 reads 18.0); the `idp_*` line must be scored
through the engine, which is what the adapter already does.

### join — sleeper_id -> gsis_id

    season    QB      RB      WR      TE       K    DEF     DL     LB     DB
      2021  100.0   98.3    96.8    99.3   100.0    0.0  100.0  100.0  100.0
      2023  100.0  100.0    99.6   100.0    96.4    0.0  100.0  100.0  100.0
      2025  100.0  100.0   100.0   100.0    94.3    0.0   84.0   88.6   83.0

Offence essentially perfect. IDP falls to 83-89% in 2024/25 because the row set swells with
fringe players absent from the crosswalk. DEF is 0% by construction -- team defences have no
gsis_id, exactly as `sim/ffa.py` documents.

### acquisition cost

Free. Undocumented public endpoint, the same read-only surface production already uses.

### what it supports

A full 2021-2025 backtest in League A's real shape -- full PPR, SUPERFLEX, deep IDP -- scored
from raw stat lines through the existing engine rather than trusting `pts_*`. Five folds, a
genuinely different league geometry from ESPN's, and **the only candidate carrying IDP
projections**. Vintage per-season ADP rides along in the same payload.

It does not support anything before 2021, and weekly/in-season replay is untested here.

---

## dynastyprocess db_fpecr — CONFIRMED as a dated ECR ranking

    file        github.com/dynastyprocess/data files/db_fpecr.parquet
    size        38,794,228 bytes, 1,830,022 rows, 24 columns
    format      RANKS ONLY. ecr, sd, best, worst, rank_delta.
                Zero points columns, zero stat columns.
    ids         FantasyPros player id, in the `id` column
    seasons     preseason snapshots 2020-2025 (six)
    pinned      data/sim-cache/dynastyprocess/db_fpecr.parquet

### two handoff premises refuted

**`fp_page` is not one page.** 94 distinct values, 117 page/type combos -- dynasty, superflex,
best-ball, IDP, rookie, weekly and ROS pages all exist, across two naming eras. But the
scoring conclusion survives intact: a search for any page mentioning half, standard or
consensus returns NONE. **Every redraft page is PPR.** There is no standard and no half-PPR
board in this file at all.

**2020 has a clean preseason board.** The handoff says 2020's snapshots start mid-season. They
do not: `2020-09-03`, 526 players, ecr 1.10-403.0. It was missed because 2020 is labelled
`page_type = "redraft-offense"` under the legacy `ppr-cheatsheets` name, so a filter on
`redraft-overall` drops it. 2019 preseason genuinely does not exist -- the file begins
2019-12-27.

    season  snapshot      players  ecr range
      2020  2020-09-03        526  1.10-403.0
      2021  2021-09-03        564  1.05-539.0
      2022  2022-09-02        545  1.63-388.0
      2023  2023-09-01        540  1.26-383.5
      2024  2024-08-30        589  1.81-546.5
      2025  2025-08-29        508  1.10-395.0

### T1 — clean, and the control proves the test has power

    2020 class(2021)= 59  leak 0      2023 class(2024)= 98  leak 0
    2021 class(2022)= 72  leak 0      2024 class(2025)= 98  leak 0
    2022 class(2023)=101  leak 0      2025 class(2026)= 82  leak 0

Control: the season's OWN class must be present, and is -- 2024 own-class 71 of 98, 2021 53 of
59. The snapshot carries rookies; it carries the right year's.

### T3 — MAE is undefined for a ranking; Spearman instead

There is no magnitude to difference. `ecr` is a rank, the outcome is points, and no monotone
map between them is part of the data. Reporting an MAE here would be inventing a scale.

Preseason ECR against realised PPR season rank:

    season   ALL     QB     RB     WR     TE
      2020  0.604  0.782  0.615  0.683  0.615
      2021  0.637  0.796  0.695  0.696  0.714
      2022  0.673  0.682  0.781  0.757  0.690
      2023  0.670  0.685  0.724  0.769  0.743
      2024  0.666  0.827  0.757  0.752  0.666
      2025  0.658  0.720  0.746  0.718  0.783

PLAUSIBLE, not contaminated. Contamination would read 0.9+. Imputing zeros for the injured and
cut moves it by at most 0.02, so it is not survivorship.

### T4 — the strongest evidence in the probe

    2021 CMC     (hamstring wk2, 7 games)  1.11 -> 1.04 -> 1.05 on 09-03
    2020 Saquon  (ACL wk2, 2 games)        2.50 -> 2.20 on 09-03
    2024 CMC     (achilles, wk10 debut)    1.27 Jul 5 -> 1.51 Aug 9
                                        -> 1.81 Aug 30 -> 2.53 Sep 6
                                           (worst blows out 8 -> 55)

That last line is a live consensus absorbing news week by week. A post-hoc rebuild would have
had him at RB40 in August.

### join — fantasypros_id -> gsis_id

Offensive skill positions 98-100% every season. The ~6% shortfall is entirely DST (0 of 32
every season -- nflverse carries no team-defence rows). The separate 85% "reaches a stat row"
figure is players who never recorded a snap, not a join failure.

### what it supports, and what it categorically cannot

**It is an ORDERING with no rulebook attached.** There is no stat line, so `score_stat_line`,
replacement levels, VORP and positional scarcity have nothing to consume. It cannot be
rescored under League A's rulebook, League B's, or any other. This is categorically unlike the
FFA and ESPN corpora, which ship stat lines and CAN be rescored. The same 508-589 rows are the
answer for all three rulebooks, because nothing in the file varies with scoring.

So it is one arm: `ffp_ecr`, a market ordering comparable to the ADP arm.

**Can a PPR-only ranking rank a standard league's board?** Only as a knowingly mismatched arm,
and the mismatch is systematic rather than noise. Mean realised rank displacement, top-150
(positive = PPR flatters him):

    2021  QB -22.1  RB  -8.2  WR +18.0  TE +18.4
    2023  QB -23.9  RB  -9.9  WR +16.8  TE +23.7
    2025  QB -24.3  RB  -9.8  WR +17.7  TE +25.0

In the top 100, mean absolute rank movement is 15-18 slots and 27-39 of 100 players move more
than 20. In an 8-team draft that is two-plus rounds of systematic positional error, always in
the same direction. **Because the file carries no reception count, this bias is
uncorrectable.** For League B it is usable only as an explicitly labelled `ecr_ppr` arm with
that magnitude reported alongside.

A SUPERFLEX board exists for 2021-2026 (QB1 at overall slot 1 vs slot 24 on the 1-QB board),
but carries no K and no DST. The IDP board is a separate ranking on its own scale with no
published interleave, and League A's IDP scoring is deliberately unusual
(`idp_tkl_solo=2`, `idp_sack=6`) against a generic consensus ordered under an unstated default.

**The one thing it has that no point projection does:** `sd`, `best` and `worst` are real
per-player expert dispersion -- the natural raw material for a risk-aware or variance-weighted
arm.

    acquisition   free. One unauthenticated curl, 38.8 MB in 0.43s.
                  Public data; unlike the FFA CSVs it needs no
                  licence gitignore.

---

## ffa average / robust — RECOMPUTABLE REFUTED, AVAILABLE CONFIRMED at no extra cost

### the high-value question, answered no

`raw_stats_<season>_wk0.csv` carries **no per-source rows**. It is one already-aggregated row
per player: `player, team, position, id, avg_type`, then `<stat>`/`<stat>_sd` pairs, then
metadata. There is no source or analyst column, no ragged rows, no appended second table, and
`avg_type` is `weighted` for 100% of rows in all nine files.

The elevated row count (1,626 against 468 projections in 2018) is not a source dimension -- it
is extra positions plus duplicate ids, which are team variants with byte-identical stats and
dual-position players projected twice. `sim/ffa.py:289` already dedupes on `id`.

All three FFA aggregations need the per-source `stat_value`, confirmed from the package source:

    summarise(robust   = wilcox.loc(stat_value, na.rm = TRUE),
              average  = mean(stat_value, na.rm = TRUE),
              weighted = weighted.mean(stat_value, w = weight))

Our files are the OUTPUT of that collapse, not its input. `_sd` gives dispersion but not the
observations, so neither an unweighted mean nor an order statistic is recoverable. Source
weighting is not recoverable either, and the package's hardcoded `default_weights` is a stale
2015 snapshot that does not match the live app -- so back-solving would be wrong even with n.

`robust` is the **Hodges-Lehmann pseudo-median** (median of Walsh averages), not Tukey
biweight. Its `w` argument is accepted and never used, so robust is strictly unweighted, and
n<=2 falls back to the mean.

### and the prize is thinner than it looks

A populated stat with an NA sd means exactly one source. Across the draftable top-200 only
55-62% of players have more than one:

    2019  multi-source 124 (62%)   single-source 76
    2025  multi-source 109 (55%)   single-source 90

For single-source players average, robust and weighted are identical by construction, and
`wilcox.loc`'s n<=2 fallback widens that further. Median `sd_pts` is 16.4 on median 198 points
in the 2025 top-100. Three aggregations of the same sources would differ on roughly half the
board by a fraction of that spread. **A genuinely thin third arm, not a tripling.**

### acquisition — available, and free given the subscription already held

FFA documents three methods (Weighted default, Mean, Robust). Historical export is
Insider-gated and in range -- back to 2008. The documented API takes `season`, `week` (0 =
seasonal) and `type` in {average, robust, weight}.

    Insider web app   $5.99/month, ALREADY HELD -> $0 extra
    FFA API           $1,000-$1,500/season -> unnecessary, not pursued
    ffanalytics R pkg free, but documents that scraping historical
                      periods will not succeed

UNRESOLVED: that the method selector appears on the HISTORICAL export screen specifically is
an inference from two FFA pages, not a demonstrated logged-in session. One Insider session --
set method to Robust, season 2021 week 0, download, check `avg_type` reads `robust` -- settles
it. Nothing was purchased.

### two corrections to the record

**`rec`/`rec_sd` are present in 2024 and 2025 ONLY.** Verified across all nine files. The FFA
README's claim of "2019, 2020, 2022, 2024 and 2025" is WRONG; `sim/ffa.py` already carries the
correct version. Receptions are not implicitly recoverable either: implied rec from the points
column is ~0 for 2023 and 52.3 median for 2025, because **2024/2025 were exported at half-PPR
and every other season at standard** (179/216 within 0.5 pts at 0.5/rec; 0/216 at 0.0 or 1.0).
`sim/boards.py:105` says the same independently. PPR is genuinely impossible before 2024.

**The accuracy claim is half misquoted and half refuted.** From FFA's own study (published
2026-06-14, covering 2014-2025):
- "sixth at 54.1 MAE" is a RUNNING-BACK-ONLY figure, not cross-position. FFA's cross-position
  numbers are FFA Average 47.4 MAE and FFA Weighted 47.8 MAE.
- "last for QB over the recent three seasons" is REFUTED. FFA Weighted was fourth-to-sixth at
  76.1 MAE; ESPN was last at 86.7. Historically at QB, FFA Weighted was third at 63.0.

This partly undercuts the premise but leaves a better argument for pulling `average`: it beats
weighted cross-position, 47.4 against 47.8, winning 64% of head-to-heads.

### a risk to flag before any second aggregation lands

`avg_type` is recorded ONLY as a column inside the raw_stats files. It is not in the filename
and not in `manifest.json`, and the `projections_*.csv` files have no `avg_type` column at all.
If a later session exports `average`, there is nowhere for it to be distinguished -- only the
sha256 would change. **A second aggregation needs `avg_type` in the filename and the manifest
before it lands.**

---

## nflverse ecosystem — one duplicate, one refutation

Checked because `nflreadpy` is already a dependency, so anything it carries is free.

### `load_ff_rankings(type="all")` — the SAME data as db_fpecr

    shape       1,830,022 x 24
    columns     identical to db_fpecr.parquet
    scrape_date 363 distinct, same range
    fp_page     94 distinct, same set
    points/stat columns: NONE

Byte-for-byte the dynastyprocess FantasyPros export, served through a loader this repo already
depends on. **Not a new source** -- but it does mean the `db_fpecr` arm needs no separate curl
and no new pinned file: `nflreadpy.load_ff_rankings(type="all")` is the whole acquisition.

Its docstring says "rankings and projections". There are zero points or stat columns. Add it to
the list of READMEs in this domain that overstate.

### `load_ff_opportunity` — REFUTED as a projection

    shape       6,054 x 159 for 2025 alone
    keys        season, week, game_id, player_id
    columns     receptions_exp, rush_yards_gained_exp,
                pass_touchdown_exp, ... (every _exp column)

Per-week, per-GAME expected stats derived from play-by-play. `receptions_exp` is expected
receptions given the targets that were actually thrown; `rush_touchdown_exp` is expected
touchdowns given the carries that actually happened. It requires the games to have been played,
so it is an OUTCOME measure, not a forecast.

REFUTED as a projection arm. It is, however, exactly the raw material for the NEXT question in
line -- whether usage signals add anything the consensus has not already priced -- so it is
worth keeping in view for that, not for this.

---

## fantasy nerds — REFUTED (free tier), UNRESOLVED (paid)

    endpoint  api.fantasynerds.com/v1/nfl/draft-projections?apikey=TEST
    format    full stat lines (passing_attempts, passing_yards,
              passing_touchdowns, rushing_*, fumbles, ...)
    ids       its own playerId

The TEST key works with no account and returns real, plausible-looking stat lines:

    season reported: 2021
    Josh Allen      4259.5 pass yd,  30.5 pass TD
    Patrick Mahomes 4619.5 pass yd,  35.5 pass TD
    Lamar Jackson   2866.5 pass yd,  26.5 pass TD

Two things kill it for this purpose.

**The sample is 30 players.** Five per position across QB/RB/WR/TE/K/DEF. T3 cannot be computed
on thirty players, and no board can be built from them.

**The `season` parameter is ignored.** Requesting `season=2024` returns `{"season": 2021, ...}`
-- the same fixed sample. So historical seasons are not addressable on the free tier, and the
one season on offer cannot be validated.

Whether a PAID key addresses history is **UNRESOLVED**. Settling it costs money, and the hard
stop says report the price and stop. Nothing was purchased and no account was created.

---

## wayback machine — UNRESOLVED, and more promising than the handoff expected

The handoff calls this a long shot and warns that a partial scrape is worse than none. On the
evidence, reachability and parseability are both better than that framing suggests. Coverage at
full pool depth is the open question.

### an early reading of mine was wrong, and the correction matters

My first CDX sweep reported nfl.com and CBS as unreachable. They were not -- archive.org
returned **HTTP 503 under throttling**, and I read a rate limit as an absence. On retry with
backoff both answered, and both are well covered. Recording this because "the archive does not
have it" and "I asked too fast" are different findings that look identical if you only ask once.

### preseason captures (Aug 1 - Sep 8) by season

    site          2018 2019 2020 2021 2022 2023 2024 2025
    nfl.com          3   10   12    3   23    9    7   15
    cbssports        2    8    5   29   12   17   10   49
    fantasypros      2    1    0    2    2    0    0    1
    fftoday         22    0    1    1    1    0    0    0

nfl.com and CBS have captures in **every season 2018-2025**. FantasyPros and FFToday do not --
three and four empty seasons respectively -- so those two are out on coverage alone.

### parseability — server-rendered HTML, real numbers

    nfl.com  2021-08-04  HTTP 200, 87,818 bytes
             <table> 1, <tr> 27, <td> 375
             contains Josh Allen, Mahomes, L.Jackson, K.Murray
             numeric cells: 267.4, 277.7

    cbs      2021-08-02  HTTP 200, 1,010,654 bytes
             <table> 1, <tr> 72, <td> 1120
             contains Josh Allen, Mahomes, L.Jackson, K.Murray
             numeric cells: 276.2, 304.6, 105.1, 290.2, 195.1

Not JS-rendered, not paywalled, not a redirect. A parser would work.

### why it is still UNRESOLVED

27 rows on the nfl.com capture is ONE PAGE of a paginated table. A full player pool needs the
pagination walked, and **every page needs its own archived capture at the same timestamp** --
which is a much stronger condition than "the site was captured that day". Nothing here
establishes that. Nor is per-position coverage settled: this tested QB-bearing pages for one
season on two sites.

What would settle it: for one target season, enumerate the paginated offsets for one site,
check how many are archived within a few days of each other, and reconstruct a single complete
positional pool. If that works for 2021 it probably works for the rest; if the pagination is
not archived, the source is dead and no amount of further CDX querying changes that.

    acquisition   scrape-and-pray. Free in money, expensive in
                  requests and wall-clock, and archive.org
                  throttles hard -- 503s throughout this probe.
                  Would need backoff and a multi-hour budget.

---

## adversarial review of the ESPN verdict

Run foreground, one agent, read-only. The verdict SURVIVED all six attacks, but the review
found one real defect the probe missed and corrected two claims the probe overstated. Both
corrections are recorded here because a wrong comment is a defect.

### DEFECT FOUND: `proTeamId` is not vintage

The probe never checked the team column. ESPN serves the player's team **as of fetch time**,
not as of that season:

    season   agrees with nflverse week-1 team
      2021              477/502   95.0%
      2022              421/493   85.4%
      2024              422/487   86.7%
      2025              452/472   95.8%

    2024 examples: Deebo Samuel espn=WAS nflverse=SF
                   DK Metcalf   espn=PIT nflverse=SEA
                   Cooper Kupp  espn=SEA nflverse=LA
                   Davante Adams espn=LA  nflverse=LV

5-15% of the projected pool carries a team the player joined AFTER that season. A 2024 board
built from this corpus that lists Deebo Samuel on Washington is leaking 2025.

**The stat lines are vintage; the team metadata is not.** Any consumer must resolve team from
nflverse for the target season and never from the payload -- no bye weeks, no stacking, no team
context from `proTeamId`. This is the same class of defect as the FFA 2019 file carrying 2020
free agency, which `assert_vintage` structurally could not see.

### CORRECTION: T3 does not have two independent yardsticks

The probe reported MAE "against ESPN's own actuals" and "against nflverse PPR, independent of
ESPN entirely" as mutual corroboration. They are the same yardstick. ESPN's `leaguedefaults/3`
season actual equals nflverse `fantasy_points_ppr` to the cent for 94-96% of skill players,
with residuals of exactly +/-2.0 from fumble accounting:

    2022 Dalvin Cook       espn 237.80   nflverse 237.80
    2022 Justin Jefferson  espn 368.66   nflverse 368.66

This does not change the verdict, but the report must not claim corroboration it does not have.
As a side effect it independently proves the `leaguedefaults/3 = full PPR` correction.

### CORRECTION: T1 passes by construction and carries almost no weight

`seasons/{YEAR}` is a season-scoped roster endpoint. It structurally cannot return a player who
debuted later:

    season  pool size   ids debuting later   present in the pool
      2018       1044                 1086                     0
      2021       1119                  569                     0
      2024       1098                  144                     0

Zero everywhere, with no exceptions -- because the endpoint cannot do otherwise. **T1 proves
the PLAYER LIST is vintage. It proves nothing about whether the NUMBERS are.** The probe's
write-up did not make that distinction. The number-vintage claim rests entirely on the
prorating test, projected-games, and T4.

The oracle itself is sound, not vacuous: class sizes 54-178 with sensible position breakdowns,
and the own-class control fires (season N's own class present at 76-100%).

### the check the probe should have run, and ESPN passes it

statId 210 on the season projection is PROJECTED GAMES -- the exact field that convicted
Sleeper 2019/2020:

    season   n   median gp   gp == actual games
      2019  150      15.54          10.0%
      2020  150      15.06           0.0%
      2021  150      16.06           0.0%
      2022  150      16.00           2.7%
      2024  150      15.00           1.3%
      2025  150      17.00          34.7%  (flat 17.0 -- frozen)

    Barkley 2020  projGP 14.12 vs actual 2
    CMC 2024      projGP 13.68 vs actual 4

Fractional expected-games values, never observed counts. Correlation with actuals is r =
0.20-0.75, against the r ~ 0.90 that convicted Sleeper.

### the decisive evidence, stronger than anything in the original probe

Prorating the projection by games ACTUALLY played should remove the bias if the number is a
frozen full-slate forecast, and should make it worse if the number already knew:

    season   n    raw bias   prorated bias   raw MAE   prorated MAE
      2019  186      +25.4            -6.8      53.8           33.8
      2021  193      +32.9            -7.9      61.6           34.0
      2022  205      +29.0            -8.4      58.0           33.7
      2025  192      +41.9            +4.5      63.4           34.5

MAE collapses from ~53-63 to ~34-43 and the bias goes to about zero. **Attrition it could not
have known about is the single largest component of its error.** No pool selection can
manufacture that.

T4 was also not cherry-picked. On a truly ex-ante pool -- top-60 per position by season N-1
actual, independent of both season-N variables -- mean bias is +13.9, median +5.4, 54.4% over,
n=1440. And the errors run both ways; the breakouts are missed as they must be:

    2018 Mahomes      proj rank 11 -> actual rank 1
    2019 L.Jackson    proj rank 17 -> actual rank 1
    2022 Geno Smith   proj rank 29 -> actual rank 5
    2024 Bucky Irving proj rank 50 -> actual rank 13

### T3's band survives every pool

    pool                        QB        RB        WR        TE
    top-40 by projection    60.3-74.6 54.5-72.1 55.4-80.3 37.8-48.5
    top-40 by ACTUAL        63.5-81.0 48.3-65.0 40.0-51.3 37.8-48.9
    all with projection>50  61.7-76.1 45.8-59.8 51.5-59.9 36.6-48.2
    union of the first two  62.2-76.8 59.8-75.6 53.6-73.4 40.5-49.3

TE runs below the 50-80 band; everything else sits in or near it. Better, the BIAS flips sign
with the selection exactly as a real forecast must -- +21 to +62 selecting on projection, -1 to
-40 selecting on actual, about zero on the union. A fitted number cannot do that.

### 2023 is worse than "empty", and that is a stronger finding

129 non-zero of 1,128 confirmed independently. The review then hunted for the projection under
every other key and found none: no other seasonId, no other scoringPeriodId, and the 482
players with a non-empty raw dict but zero appliedTotal carry **exactly one key each, `{'210':
...}`** -- projected games and no production stats at all.

The only surviving 2023 signals are `split=2` and the weekly sum, and both are CONTAMINATED
(see below). So 2023 is not merely unusable; the parts that remain would actively inject
hindsight.

### a warning the probe's own table understated

`split=1` (weekly) and `split=2` are CONTAMINATED and must never be used as a fallback:

    2020 Barkley  season proj 288.62 | weeklies: wk1 19.2, wk2 20.3,
                  wk3-17 all 0.0 | split2 = 0.0
    2024 CMC      season proj 335.49 | wk1-9 0.0, wk10-13 ~20, then 0
                  | split2 = 0.0
    2022 D.Cook (healthy control)                    | split2 = 17.20

The weeklies collapse to 0.0 the moment a player is ruled out. The season total sits at 288.6
anyway -- which is what proves `split=0` is not a rollup of them. The probe labelled `split=2`
neutrally as "(per-game projection)"; it is a LAST-KNOWN per-game rate and carries hindsight.

### smaller corrections

- "45 statIds per row" is McCaffrey specifically. Across the 2021 projected pool the count is
  median 38, min 5, max 68.
- The realised-outcome join is 97-100% on the top-200, slightly BETTER than the probe's
  reported 96.7-98.3%. Residuals are players who were projected and never played (A.J. Green
  2019, Michael Thomas 2021, Joe Mixon and Brandon Aiyuk 2025), which is correct.
- Crosswalk rows with both espn_id and gsis_id: 7,930, not the 7,917 the probe reported.
- When is the snapshot taken? Late preseason. Players ruled out before week 1 are already
  zeroed or absent (Cam Akers 2021, Damien Williams 2020 opt-out), while murky cases are
  hedged rather than zeroed (Joe Mixon 2025 proj 118.1 at projGP 9.00). That is a late-August
  board behaving as a draft-day board should.

---

## adversarial review of the Sleeper verdict

Foreground, one agent, read-only. The 2021 boundary SURVIVED and is better supported than the
probe argued. One claim was OVERTURNED, and it is the same defect the ESPN review found.

### the 2021 boundary is sharp, on five independent axes

The prorating test is the one that settles it. Prorate each projection by games actually
played: a frozen full-slate number should see its bias collapse toward zero, while a number
that already knew the games should get WORSE.

    season  MAE -> prorated   bias -> prorated   r(proj, actual games)
      2019  28.8 ->  30.4     +5.6 ->  +11.1                    0.323
      2020  24.4 ->  26.3     +5.9 ->   +7.9                    0.353
      2021  67.6 ->  31.7    +52.8 ->  +10.1                    0.139
      2022  50.7 ->  25.5    +34.6 ->  -11.0                    0.033
      2024  56.0 ->  38.2    +24.4 ->  -22.3                    0.169
      2025  66.5 ->  34.7    +39.0 ->  -11.7                    0.063

2021-2025 collapse. 2019/2020 get worse, because their games dimension is already truth and
there is nothing left to prorate. The residual bias also flips sign across the good seasons,
which is ordinary forecast error rather than a fit.

`gp` is structural, not a threshold: 2018-2020 carry SIXTEEN distinct values, 2021-2025 carry
TWO (17.0 or 18.0, plus 1.0 for the 32 DEF rows).

The best alternative defence of 2019/2020 -- that `gp` is a lookback feature from the prior
season -- was tested and killed: 2020's `gp` matches season-2020 actual games 71% of the time
and season-2019 actual games only 16%.

Per-stat correlation with realised totals is the cleanest discriminator of all:

    season   WR/TE rec   RB rush yd   QB pass yd
      2019        0.91         0.94         0.98
      2020        0.89         0.94         0.98
      2021        0.41         0.65         0.86
      2024        0.52         0.67         0.87
      2025        0.46         0.67         0.80

An r of 0.94 between a preseason projection of rushing yards and the realised total is not
achievable by any forecaster. 0.65 is.

### OVERTURNED: Sleeper's `team` is end-of-season, not preseason

Same defect class as ESPN's `proTeamId`, and worse. For mid-season movers:

    season  movers  = week-1 team   = last-week team
      2021      24        0   (0%)        23  (96%)
      2022      26        0   (0%)        25  (96%)
      2023      12        0   (0%)        12 (100%)
      2024      13        0   (0%)        13 (100%)
      2025      21        0   (0%)        20  (95%)

Zero percent week-1. 95-100% end-of-season. Every 2024 mover:

    Amari Cooper    BUF (wk1 CLE)    Davante Adams   NYJ (wk1 LV)
    DeAndre Hopkins KC  (wk1 TEN)    Diontae Johnson HOU (wk1 CAR)
    Mike Williams   PIT (wk1 NYJ)    Daniel Jones    MIN (wk1 NYG)
    Cam Akers       MIN (wk1 HOU)    Khalil Herbert  CIN (wk1 CHI)

Overall pool disagreement 2.5-8.2% for 2020-2025.

**The nested `player` object is far worse -- it is a FETCH-TIME snapshot.** `player.team`
disagrees with the week-1 team for 93% of the top 400 in 2019, 86% in 2021, 52% in 2024, 33%
in 2025. Monotone decay with recency is the textbook signature. CMC's 2021 row carries
`player.team = "SF"` and a `metadata.injury_override_regular_2024_14` key.

**So both confirmed stat-line corpora have a non-vintage team field.** The projection NUMBERS
are vintage in both; the roster metadata is not, in either. Resolve team from nflverse for the
target season, and never read Sleeper's `player.*` for anything historical.

### three probe numbers corrected

**`last_modified` is not "January of the following year for each past season".** It exists
only for 2022-2025; 2017-2021 are NULL. And the stamp is anti-correlated with contamination --
2021 has no stamp and is clean, 2019/2020 have no stamp and are contaminated. The write
signature is a bulk table scan at 415-688 rows/sec, 92-93% monotone in numeric `player_id`
with the string-id DEF rows last: a migration, not a model run. The live 2026 file settles the
semantics -- all 7,903 rows stamped inside a 14-second window on the fetch date.

**The blanked-stub population is 383-699 per season, not 11-17.** The probe's headline number
does not reproduce under any definition. But the figure the conclusion actually rests on --
0-3 at draft depth -- is exactly right:

    season  adp<=50  adp<=100  adp<=200  adp<=300
      2021        0         1         2        32
      2022        1         2         3        51
      2023        1         2         3        56
      2024        0         1         2        26
      2025        0         0         0        67

The extras are deep-tail camp bodies and long-retired names at adp 240-300 with zero games --
noise, not survivorship.

**The blanking is INCONSISTENT, which argues against a systematic post-season sweep.** In 2025
Joe Mixon (adp 83.1), Brandon Aiyuk (131.9) and Tyler Bass (179.7) all played zero games and
KEPT full projections of 117.9, 107.0 and 98.0. Blanking tracks "played a few games then went
on IR", not "missed the season".

### two claims strengthened

**T1 is stronger for Sleeper than for ESPN.** Where ESPN's T1 passes by construction, Sleeper
physically returns the future-draftee rows -- and not one of them carries numbers:

    season  future rows present   with numbers
      2021                 1692              0
      2023                  896              0
      2025                  215              0

**The best positive evidence in either probe** is the reverse check. Players whose last NFL
season predates the file still carry projections: 40 of 1,278 in 2021, 118 of 1,527 in 2025.
2025 Joe Mixon at 117.9 points and ADP 83.1 with zero games played; Blake Bortles projected
54.0 in 2021, having last played in 2019. **A file recomputed or filtered after the season
could not contain those rows.**

### `pts_half_ppr` is exactly reproducible for 2021+, and the IDP warning is confirmed

    season      within 0.5 of a hand-scored line
      2019      7/150
      2020     26/150
      2021-24  150/150
      2025     149/150

`pts_ppr - pts_half_ppr == 0.5 * rec` with zero violations in every season. So for offence
from 2021 the shortcut and the stat line agree, and either path works. 2019/2020 failing this
is one more break at the same boundary.

For IDP the warning holds: `pts_std == pts_half_ppr == pts_ppr` on every IDP row, which is
impossible if PPR distinctions were applied. 2024 T.J. Watt reads 27.0 against a line of 45
solo tackles, 14 assists and 15 sacks -- worth 200+ under League A's `idp_tkl_solo = 2`,
`idp_sack = 6`. **`pts_*` must be discarded for IDP and the granular line rescored.**

`idp_*` keys exist from 2020; 2018/2019 carry the same data under legacy names (`tkl`,
`tkl_solo`, `tkl_ast`, `sack`, `ff`, `int`).
