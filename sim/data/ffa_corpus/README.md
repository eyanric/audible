# FFAnalytics projection corpus — scraped, verified, gitignored

The CSVs here are **never committed**. This repository is public and the data comes from a
paid FFA Insider subscription. Only this README, `COVERAGE.md` and `manifest.jsonl` are tracked, and
`sim/test_g_ffa_scrape.py` asserts that no `.csv` is tracked *anywhere* in the repository —
not just in this directory, because a file dropped in the wrong place is exactly how paid
data reaches a public remote.

Everything here is written by `sim/tools/ffa_scrape/`. Do not hand-place files: a file whose
name this tool did not emit is reported by `status` as unnameable, and one with no manifest
entry is reported as unvouched.

```
uv run python -m sim.tools.ffa_scrape login                    # once, a human signs in
uv run python -m sim.tools.ffa_scrape probe                    # re-measure the app
uv run python -m sim.tools.ffa_scrape run --stage weekly-weighted
uv run python -m sim.tools.ffa_scrape status --gaps
```

## Why a tool and not a script

A prior attempt drove the app by hand from a chat session and shipped **36 mislabelled
files** before a guard caught the cause. It failed three ways:

- **No test cycle.** Every behaviour was discovered by shipping broken output.
- **No persistence.** State lived in page memory. A shinyapps.io session reload wiped the
  runner mid-flight and nothing on disk recorded what had completed.
- **Filename collisions.** Browser downloads meant Chrome appended `(1)`, `(2)` on re-runs,
  and the *first* download claimed the clean name — so a contaminated early file kept the
  good name and a correct later one got suffixed. `ffa_raw_2019_wk0_average.csv` and
  `..._robust.csv` both ended up holding `weighted` data.

So this tool writes files from Python with the exact name, verifies every raw payload
against the aggregation it asked for *before* the payload reaches disk, and appends a
manifest line only after a success.

## What the app does

**URL** `https://ffashiny.shinyapps.io/newApp/` — the standalone Shiny app. The public site
embeds it in a cross-origin iframe, which `page.evaluate` cannot reach at all; go direct.

**Auth** is the app's own navbar login. A human signs in once and a Playwright persistent
profile carries the session. The profile lives at `data/sim-cache/ffa_profile` (gitignored,
because it holds a live session cookie for a paid account). **The tool never handles the
password.**

**Controls** — all `selectize` widgets, set with `el.selectize.setValue(value, false)`:

| input id | values |
| --- | --- |
| `sidebar-year-drop` | 2008–2026. Labels read "2019-2020"; the VALUE is the START year. |
| `sidebar-week-drop` | 0 = full season, 1–17 regular, 18–21 playoffs. |
| `settings_page-data_aggregation_box-average_type-drop` | `weighted` \| `average` \| `robust` |
| `projections_page-proj-download_choice-drop` | `proj` \| `raw` |

**Tabs** `a[data-value="tab_proj"]`, `a[data-value="tab_settings"]`.

**Download** `a#projections_page-proj-download_projections-download`. Its `href` is
session-bound:

```
session/<32 hex>/download/
    projections_page-proj-download_projections-download?w=<32 hex>
```

RELATIVE, with no worker prefix — measured on a live logged-in session. An earlier version of
this section documented the absolute `/newApp/_w_<worker>/session/<id>/…` form, which
`driver.py` records as measured false and which contradicted this README's own later bullet.

There is no parameterised URL, so a plain HTTP loop is impossible. Inputs must be set through
a live Shiny session and the file fetched from that session's own endpoint. The link's text
is the login state: `Download` when the subscription is live, `Subscribe to download`
otherwise.

## The five behaviours the driver is shaped around

1. **Changing the year resets the aggregation to `weighted` server-side.** This is what
   produced the 36 mislabelled files. The driver therefore sets the year FIRST and the
   aggregation AFTER, on every single job — there is no "it is already set" fast path,
   because that assumption *is* the defect.
2. **An aggregation only takes effect after a Settings → Projections round trip**, with a
   long settle. Setting it while on the Projections page changes the widget and not the
   server: the page reads `average` and serves `weighted`.
3. **`weighted` needs no Settings trip *after a real year change***, because that is what
   leaves the app on weighted. Writing 2019 over 2019 is not a change and resets nothing —
   the unqualified form of this sentence *is* the defect, and the driver skipping the trip on
   the strength of a reset that had not happened is what served `robust` for a `weighted`
   request. Measured cost after the stage-4 reordering: weighted weekly files averaged 17.2s
   and average/robust 19.5s — 88% of each other, not a third, because the Settings trip is
   now paid twice a season rather than once a file.
4. **`avg_type` is the fifth column of every `raw` file**, so each raw download self-verifies.
   **`proj` files have no such column and cannot be verified this way** — the manifest records
   their `measured_avg_type` as `null` rather than echoing the request back, and the corpus
   prefers `raw`.
5. **The Position dropdown filters the CHART only.** A download carries every position the
   app has *for that scope* — which is not always nine.

## Two corollaries the handoff did not have, both measured live

**A year change only resets the aggregation when the year actually changes.** Writing 2019
over 2019 is not a change and resets nothing. Measured: one job after a `robust` one in the
same season, the app served `robust` for a `weighted` request —

```
weekly-2019-wk5: asked for 'weighted', file holds ['robust']
```

The verifier rejected it rather than letting it land mislabelled, which is what the verifier
is for. But a run where a third of the jobs fail is not a run, so the driver tracks the
**effective** aggregation — what the server will serve, which is not what the widget reads —
and takes the Settings trip whenever that is not already what the job wants. Seventeen weekly
jobs in one season cost at most one trip between them. A fresh or re-established session
knows nothing and pays for a trip rather than assuming a reload left things on `weighted`.

**IDP is a property of the week, not of the season.** There is no clean boundary year — an
early reading of the first two seasons suggested 2015 → 2016 and that was wrong. Measured:

```
2015 wk1-17   no IDP, every week
2016 wk1-12      IDP     2016 wk13-17        no IDP
2017 wk1-6,8,9   IDP     2017 wk7, wk10-17   no IDP
```

And the IDP-less weeks come in **two different shapes**, which matters more than the flag:

```
2015 wk10   1099 rows  6 pos   WR 414  RB 257  TE 212   deep offense, no IDP
2016 wk12   1236 rows  9 pos   WR 266  RB 204           full
2016 wk13    587 rows  6 pos   WR 203  RB 140           IDP gone AND offense halved
2017 wk07    549 rows  6 pos   WR 176  RB 138           same
2017 wk08    951 rows  9 pos   WR 224  RB 184           full again the next week
```

2015 is a season whose contributing sources did no IDP but went deep on offence. 2016 wk13-17,
and 2017 wk7 and wk10-17, lose IDP *and* roughly half their offensive depth — a source dropped out for
those weeks. Neither is a defective download: zero ragged rows, complete CSV documents,
stable hashes.

So **the six offensive and special-teams positions are required everywhere** — that is the
check that catches a filtered or truncated download — and IDP is recorded instead,
all-or-nothing: two of the three is a broken file rather than a narrow one. `COVERAGE.md`
names every IDP-less file **and every thin week**, because a weekly analysis that averages
over wk7 2017 without knowing it holds 549 players rather than 1139 is drawing on a different
population and will not say so.

**Sessions drop.** shinyapps.io reloads on idle or on resource caps, resetting the year to
2026, the week to 0 and the file type to `proj` — confirmed live. That is the expected path
over a run of hundreds of files, not an exceptional one, so every input is read back after it
is written *and* all of them are re-read together before the fetch — a reload that lands just
before the last write leaves that input looking right and the earlier ones reverted.

The settle timings are **empirical, not documented**, and may be load-dependent. `probe`
re-measures behaviours 1–4 and the reload defaults against the live app; the offline gates
that assert the same three facts are marked out of scope in `mutate.py` for exactly that
reason — no edit to the driver can make a model wrong, only a measurement can.

## Three more things the app does that no documentation says

- **The download href is relative** — `session/<id>/download/…?w=…`, with no `/newApp/_w_<n>/`
  prefix. Reading the session token by splitting on `/session/` finds nothing and returns
  `None` for a perfectly healthy session.
- **Five outputs never stop recalculating.** `settings_page-settings_tiering_ui`,
  `optimizer_page-optimizer-optimizer_display_ui`, `accuracy_page-acc_ui`,
  `account_page-user_subscription_box-cportal` and `controlbar-help_links` carry
  `.recalculating` forever, because Shiny never resolves an output on a tab that is never
  rendered. "Nothing is recalculating" is a predicate that cannot be true here, and waiting
  for it costs the full timeout on every call. `.shiny-busy` is never set either. So the
  driver keeps a **stuck set**: seeded at establish time, and grown whenever an output stays
  continuously busy past `stuck_after` — the first Settings trip reveals more of them.
- **The widgets populate long after the DOM exists.** `wait_for_selector` on the download
  link returns while the year dropdown is still empty; a headless session read `year=''`,
  `week=''` and an empty control text and would have fetched against it. The driver waits on
  *populated* state, and takes the idle baseline only after that — captured mid-load it was
  nine outputs rather than five, and would have swallowed real work all session.

Also: `el.options` on a selectize widget holds **only the selected value**. The other options
live in `el.selectize.options`. Reading the DOM select reports a one-item list for every
dropdown on the page.

## Filenames

```
ffa_{kind}_{year}_wk{week}_{avg}.csv
```

`kind` ∈ `raw`, `proj`. `avg` ∈ `weighted`, `average`, `robust`. Week is a plain integer, so
`wk0` and `wk17`, never `wk00`. `naming.parse_filename` refuses anything this tool did not
emit — including a Chrome `(1)` suffix, which is the shape that made the prior contamination
unrecoverable.

## manifest.jsonl

One JSON object per line, appended after each verified success and fsynced before the job is
believed to be done. JSONL rather than a document because appending a line cannot corrupt the
lines already written, and a torn final line from a kill mid-write is discardable rather than
fatal.

Every field, and what each is for:

```json
{"avg": "weighted",
 "bytes": 772033,
 "fetched_at": "2026-09-10T12:00:00+00:00",
 "file": "ffa_raw_2019_wk0_weighted.csv",
 "kind": "raw",
 "measured_avg_type": "weighted",
 "positions": {"DB": 398, "DL": 351, "DST": 33, "K": 57, "LB": 309,
               "QB": 157, "RB": 291, "TE": 218, "WR": 422},
 "rows": 2236,
 "sha256": "...",
 "week": 0,
 "witness_sha256": null,
 "year": 2019}
```

| field | meaning |
| --- | --- |
| `avg` | the aggregation **requested** |
| `measured_avg_type` | what the fifth column **actually said**. `null` for `proj`, which has no such column — never an echo of `avg` |
| `witness_sha256` | for a `proj` file, the sha256 of the raw file fetched from the same session state immediately before it, whose fifth column *did* carry the aggregation. `null` for `raw`, which vouches for itself |
| `sha256` | of the payload bytes, so a run can assert it read the bytes the artifact claims without the bytes being in git |
| `bytes` | length on disk; `plan` compares this **and** the digest |
| `rows` | data rows, excluding the header |
| `positions` | counts per position, which is where the IDP map comes from |

A failed job is recorded in `failures.jsonl` instead and **no file is written**, so a file
that failed verification never reaches disk.

The file lands *before* its manifest line, so a kill in the microseconds between them leaves
a file with no entry. That is the safe direction: `plan` re-fetches a file the manifest does
not name, and `status` reports it as UNVOUCHED. The reverse order would leave an entry
vouching for bytes that are not there. (An earlier version of this README claimed a corpus
"can never contain a file the manifest does not vouch for" — that was an overclaim.)

## 2015 weekly WEIGHTED carries standard deviations with no point estimates

**Sixteen files — 2015 weeks 2–17, `weighted` only — hold `X_sd` populated while `X` is `NA`
for 93–95% of the paired cells.** Every other file in the corpus is at 0.0%.

```
ffa_raw_2015_wk2_weighted.csv    6145 sd-populated cells, 5858 with the value NA = 95.3%
ffa_raw_2015_wk10_weighted.csv   6288 sd-populated cells, 5861 with the value NA = 93.2%
ffa_raw_2016_wk2_weighted.csv    8113 sd-populated cells,    0 with the value NA =  0.0%
ffa_raw_2019_wk5_weighted.csv    6451 sd-populated cells,    0 with the value NA =  0.0%
```

Do not measure a raw NA rate instead: ~81% of point-estimate cells are legitimately `NA`
corpus-wide, because a receiver has no passing yards. The anomaly is specifically an `sd`
without its value.

**2015 wk1 weighted is clean, and 2015 `average` and `robust` are clean in every week.** So
2015 weekly data is usable — *from the alternate aggregations*, not from weighted. Any model
reading weighted point estimates should treat its usable weekly window as **2016–2025**, or
use `average`/`robust` for 2015.

Nothing in `verify_payload` looks at cell values, which is why these 16 files passed: they are
structurally perfect — right aggregation, right scope, right positions, no ragged rows.

## THE RAW SCHEMA IS NOT ONE SHAPE — read this before joining anything

There are **three** `raw` column sets. Concatenating files without aligning columns silently
produces wrong answers, and the two omissions are both scoring-relevant.

```
65 cols  535 files  the full schema
63 cols   19 files  season (wk0) average and robust, every year, plus 2026 weighted
                    -- LACKS rec, rec_sd
55 cols   31 files  2015 wk1-17, 2016 wk13-17, 2017 wk7 and wk10-17
                    -- LACKS all ten idp_* columns
```

### `rec` is in the weighted season files and nothing else

```
2018-2025 wk0 weighted   65 cols   rec present
2018-2026 wk0 average    63 cols   rec ABSENT
2018-2026 wk0 robust     63 cols   rec ABSENT
2026      wk0 weighted   63 cols   rec ABSENT
every weekly file        65 cols   rec present
```

`sim/ffa.py` already carries the warning this earns: *"A missing scoring key must raise,
never default to zero — a PPR board scored with silent zeros looks entirely plausible and is
not."*

**Both leagues pay per reception.** `sleeper_boyfun` is half-PPR; `espn_davis_drive` targets
half-PPR. So **the season-level `average` and `robust` files cannot score either league**, and
neither can 2026 weighted. Season-level PPR scoring is available from `weighted` 2018–2025
only.

The weekly files are the exception and it is the good one: all 535 carry `rec`, populated —
spot-checked at ~6–7 receptions for a lead WR in a week and ~103–119 across a season. **PPR is
scoreable weekly across all three aggregations**, which it was not at season level. That is a
concrete thing the weekly corpus buys that the season corpus could not give.

### IDP: an absent column is not an empty one

```
IDP columns absent entirely       31 files
IDP columns present, no IDP rows  62 files
                                  -- 93 files with no defenders, two different shapes
```

Reading `idp_solo` from one of the 31 raises `KeyError`; from one of the 62 it returns a
column with no defenders in it. A loader that tolerates the second and not the first — or
that treats both as zero — is the silent-zeros failure again, on the IDP axis.

## What is actually in each file

**`raw` — the stat lines.** 65 columns in 535 of 585 files (see the three shapes above; 63
is the rec-less season shape and 55 the IDP-less weekly one): passing, rushing, receiving, kicking by distance
band, team-defence and IDP counts, each with a standard deviation, plus `draft_year`,
`birthdate`, injury fields and the `season_year`/`week` scope columns. **This is what a
league-specific board needs**, because points are computed from the stat line under *your*
scoring, not taken from somebody else's total.

**`proj` — FFA's own scored projection.** 22 columns: `points`, `sd_pts`, `dropoff`, `floor`,
`ceiling`, `points_vor`, `floor_vor`, `ceiling_vor`, `rank`, `position_rank`, `tier`, `adp`,
`aav`, `uncertainty`. Two things about it matter and both are easy to miss:

1. **It is scored under the FFAnalytics default league**, not yours. `points` and every
   `_vor` column embed a scoring system and a roster that are not `sleeper_boyfun` or
   `espn_davis_drive`. Using them as a board is using someone else's league's answer.
2. **It has no `avg_type` column**, so a `proj` file cannot say which aggregation produced
   it. That is why every one carries a `witness_sha256`.

**So: `raw` for anything league-specific, `proj` only for FFA's own ranking, `adp`/`aav`, and
the uncertainty columns the raw lines do not carry.**

`proj` is also **truncated to a fixed count per position** — see `COVERAGE.md` for the grid.
Across every season pair it holds 44% of the raw pool, and the shortfall is worst exactly
where a deep league needs depth: WR 32%, TE 28%, DB 36%. For a 10-team SUPERFLEX league a
`proj`-derived board has **36 quarterbacks in total**.

## Coverage

**612 files, 169,215,471 bytes. Complete apart from three named holes.**

```
weekly raw  2015-2025 wk1-17  x weighted   186/187
weekly raw  2015-2025 wk1-17  x average    186/187
weekly raw  2015-2025 wk1-17  x robust     186/187
season raw  2018-2026 wk0     x all three   27/27
season proj 2018-2026 wk0     x all three   27/27
```

That is **177,885 data rows** in the weighted weekly files alone and **533,655** across all
558 weekly files, against the ~2,400 player-seasons every measurement in this project ran on
before it. (An earlier version of this line said "~43,000 player-weeks", which was computed
from the season pool rather than from the data and understated it about fourfold.)

See `COVERAGE.md` beside this file — the per-season/week grid, the IDP map, the `proj` depth
table and the per-file list — regenerated from the manifest by
`uv run python -m sim.tools.ffa_scrape status --write-coverage`. **Gaps are named, never
substituted.**

### Do the three aggregations differ? Yes.

186 weekly weeks hold two or more aggregations and **no pair is byte-identical** — nor is any
pair identical after stripping the `avg_type` column, which is the check that would catch a
relabelled copy. Same players, different projections.

**They are NOT monotonic.** 22 of the 186 weekly scopes have `average` larger than `weighted`,
and they are exactly the IDP-less ones — all of 2015, and 2016 wk13-17. An earlier version of
this line asserted monotonicity from the four examples below; most scopes are monotonic and it
is not a property you may rely on.

Note also that `2018 wk0` is a *season* scope, and its `average`/`robust` exports have two
fewer columns than its `weighted` one (no `rec`/`rec_sd`), so part of that byte drop is schema
rather than different numbers.

```
2018 wk0   weighted 580500B  average 498114B  robust 416777B   1624 rows each
2019 wk5   weighted 470159B  average 425688B  robust 358621B   1309 rows each
2022 wk8   weighted 254324B  average 226883B  robust 190952B    702 rows each
2025 wk12  weighted 286602B  average 259689B  robust 227409B    887 rows each
```

### The three gaps: 2020 week 17, all aggregations

Not a scraper failure. FFA has no usable data for that scope, and says so three different
ways. Measured against controls either side:

```
raw  2020 wk16 weighted  200  170355 B  521 rows  all 9 positions   fine
raw  2020 wk17 weighted  200      23 B    1 row   1 column, head "x"
raw  2020 wk17 average   200    1577 B    3 rows  DB, DL, LB only
proj 2020 wk17 weighted  500     223 B  "An error has occurred"
raw  2020 wk18 weighted  200   80840 B  238 rows  all 9 positions   fine
raw  2021 wk17 weighted  200  225808 B  623 rows  all 9 positions   fine
```

Week 16 and playoff week 18 are both healthy, and week 17 of the next season is healthy.
The `weighted` response is a degenerate one-column frame; the `average` response is a
well-formed 65-column CSV holding three defensive players and nothing else; `proj` returns
a 500. The verifier rejected all three, which is the correct outcome for each.

Stage 4 then re-tested the same scope in a later run -- 5h48m after the first rejection, the
same working day -- and got the same answer for both remaining aggregations:

```
ffa_raw_2020_wk17_average.csv   3 rows, only DB/DL/LB   rejected, twice
ffa_raw_2020_wk17_robust.csv    3 rows, only DB/DL/LB   rejected, twice
```

Both were retried with doubled settles and a forced Settings round trip. **Two runs, three
aggregations, same result: FFA has no week 17 of 2020.** (An earlier version of this line
claimed three independent sessions two months apart; the `failures.jsonl` timestamps are
2026-09-10T18:25:30Z for weighted and 2026-09-11T00:13:16Z and 00:19:42Z for average and
robust, six minutes apart inside one continuous stage-4 run.) The
three absent files are the corpus's only holes.

**Do not substitute week 16 or 18 for it.** A weekly model that silently fills this in is
modelling a week that FFA never projected.

`failures.jsonl` in this directory carries the per-attempt record, and is gitignored because
it is run-local.

## Do not extend the window before 2018

`sim/data/ffa/README.md` records why: player counts collapse from roughly 450–470 to about
240 at 2016–2017, and replacement level is defined as the best projected player nobody
rosters, so a short pool lets the baseline fall off the end and read 0.0. A truncated pool
systematically inflates the one arm whose entire mechanism is replacement level. Weekly data
reaches back to 2015 and is fetched from there because a weekly pool is a different question
from a season replacement baseline — but no season-level arm should read 2015–2017.
