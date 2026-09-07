# FFA vintage projections — drop directory

Put the FFA Insider exports here. **The CSVs are gitignored and must stay that way**:
this repository is public and the files come from a paid subscription. Only this README
and `manifest.json` are committed.

Two files per season, exactly as exported:

```
sim/data/ffa/raw_stats_<season>_wk0.csv
sim/data/ffa/projections_<season>_wk0.csv
```

## Why these files matter

Every prior sim session concluded that vintage preseason projections did not exist. The
`ffanalytics` package documents that scraping historical periods will not succeed because
sites overwrite their projections, and two sessions searched every pinned source and found
none. That is why `sim/`'s board was built from ADP rank, and why B2's and B3's arm
comparisons measured the ordering overlay rather than Audible's value layer.

These files close that gap. They are the projections **as they stood before each draft**.

## Vintage verification — already done, re-run it anyway

Each season's file was checked for the *following* year's draft class. A file re-generated
by today's model would contain them; a genuine vintage file cannot.

```
2019 file: 2020 rookies present -> NONE
2020 file: 2021 rookies present -> NONE
2021 file: 2022 rookies present -> NONE
2022 file: 2023 rookies present -> NONE
2023 file: 2024 rookies present -> NONE
2024 file: 2025 rookies present -> NONE
```

Checked names included Trevor Lawrence, Breece Hall, Bijan Robinson, Caleb Williams,
Cam Ward and Ashton Jeanty. **Re-run this as a gate for any season added later.** It is
cheap and it is the only thing standing between this dataset and a silent leak.

## What the raw_stats files contain

Full **stat lines**, not point totals — which is what makes them usable. Passing, rushing
and receiving counts, plus per-stat standard deviations, plus the columns that were missing
before:

- `fg_0019` … `fg_50`, `xp` — kickers score for the first time
- `dst_int`, `dst_sacks`, `dst_safety`, `dst_td`, `dst_blk` — defences score for the first time
- `idp_solo`, `idp_sack`, `idp_int`, `idp_pd`, `idp_td` — IDP leagues become testable

Two of nine starting slots scored exactly 0.0 in every simulation run before this.

`avg_type` is `weighted` in every file exported so far. FFA also computes `average` and
`robust`; those are separate consensus aggregations, not reformats, and are worth pulling.

## Known gaps — handle explicitly, never by default

**`rec` and `rec_sd` are absent from 2021 and 2023.** Present in 2019, 2020, 2022, 2024
and 2025. `rec_yds` and `rec_tds` are present in all seven.

This is harmless for `espn_green_hope` (standard, `rec = 0.0`) and **wrong** for
`espn_danger_zone` (1.0/rec for WR and TE) and `sleeper_boyfun` (full PPR). A missing
scoring key must **raise**, never default to zero — a PPR board scored with silent zeros
looks entirely plausible and is not.

Usable seasons therefore differ by league, and a run artifact must record which it used:

```
standard scoring   2019-2025   (all seven)
PPR scoring        2019, 2020, 2022, 2024, 2025
```

Separately, `sim/`'s weekly actuals are pinned 2021–2025. **2019 and 2020 need a weekly
backfill** through the existing `pin_season` path before either is scoreable.

## Do not extend the window before 2018

Player counts collapse from roughly 450–470 to about 240 at 2016–2017. That is not merely
thin — replacement level is defined as the best projected player nobody rosters, so a short
pool lets the baseline fall off the end and read 0.0. A prior review found exactly this
happening with 18 tight ends against 18 rostered, which handed every tight end his full
projection as VORP and put Brock Bowers first overall.

A truncated pool systematically inflates the one arm whose entire mechanism is replacement
level. It would look like the transform suddenly working.

**Gate it:** assert the projected pool exceeds the drafted pool by a real margin, per
season, so a thin pool fails loudly.

## The join is the first thing to prove

Player ids look like MFL ids — Joe Burrow is `14777` in both the 2024 and 2025 files.
DynastyProcess `db_playerids`, already pinned as `ff_playerids`, carries `mfl_id` beside
`gsis_id`.

**Prove the match rate before any arm runs.** `weekly.prior_points` once looked players up
with `ffc####` keys against a roster keyed on gsis ids; every lookup missed, every prior
read 0.0, and because `optimal_week` is an exact matching, every lineup tied and fell out of
the tie-break. Two sessions of headline numbers were computed against arbitrary lineups
before anyone noticed.

A silent join failure here produces a board built entirely from defaults that looks
completely reasonable.

## manifest.json

Records `season`, `file`, `sha256`, `rows`, and the column set, so a run can assert it
loaded the same bytes the artifact claims without the data being in git. Regenerate it
whenever a season is added.
