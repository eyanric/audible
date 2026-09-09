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
