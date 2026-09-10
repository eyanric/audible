# FFAnalytics projection corpus — scraped, verified, gitignored

The CSVs here are **never committed**. This repository is public and the data comes from a
paid FFA Insider subscription. Only this README and `manifest.jsonl` are tracked, and
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
/newApp/_w_<worker>/session/<sessionId>/download/
    projections_page-proj-download_projections-download?w=<worker>
```

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
3. **`weighted` needs no Settings trip at all**, because a year change already leaves it
   there. Those jobs cost roughly a third of the others, which is why the stage order
   front-loads them.
4. **`avg_type` is the fifth column of every `raw` file**, so each raw download self-verifies.
   **`proj` files have no such column and cannot be verified this way** — the manifest records
   their `measured_avg_type` as `null` rather than echoing the request back, and the corpus
   prefers `raw`.
5. **The Position dropdown filters the CHART only.** Downloads always carry all nine
   positions, which is what makes the completeness check meaningful.

**Sessions drop.** shinyapps.io reloads on idle or on resource caps, resetting the year to
2026, the week to 0 and the file type to `proj`. That is the expected path over a run of
hundreds of files, not an exceptional one, so every input is read back after it is written
*and* all of them are re-read together before the fetch — a reload that lands just before the
last write leaves that input looking right and the earlier ones reverted.

The settle timings are **empirical, not documented**, and may be load-dependent. `probe`
re-measures behaviours 1–4 and the reload defaults against the live app; the offline gates
that assert the same three facts are marked out of scope in `mutate.py` for exactly that
reason — no edit to the driver can make a model wrong, only a measurement can.

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

```json
{"avg":"weighted","bytes":700698,"favg":null,"file":"ffa_raw_2019_wk0_weighted.csv",
 "fetched_at":"2026-09-10T12:00:00+00:00","kind":"raw","measured_avg_type":"weighted",
 "positions":{"DB":399,"DL":351,"DST":33,"K":57,"LB":309,"QB":158,"RB":291,"TE":218,"WR":422},
 "rows":2238,"sha256":"...","week":0,"year":2019}
```

`sha256` is of the payload bytes, so a run can assert it read the same bytes the artifact
claims without the bytes being in git. `measured_avg_type` is what the fifth column actually
said — `null` for `proj`, which carries no such column.

A failed job is recorded in `failures.jsonl` instead, and **no file is written**. A corpus
directory can therefore never contain a file the manifest does not vouch for, which is what
makes the resume rule sound: a job is done only when the manifest names it AND a file of the
recorded size sits beside it.

## Coverage

See `COVERAGE.md` beside this file, regenerated from the manifest by
`uv run python -m sim.tools.ffa_scrape status --gaps`. **Gaps are named, never substituted.**

## Do not extend the window before 2018

`sim/data/ffa/README.md` records why: player counts collapse from roughly 450–470 to about
240 at 2016–2017, and replacement level is defined as the best projected player nobody
rosters, so a short pool lets the baseline fall off the end and read 0.0. A truncated pool
systematically inflates the one arm whose entire mechanism is replacement level. Weekly data
reaches back to 2015 and is fetched from there because a weekly pool is a different question
from a season replacement baseline — but no season-level arm should read 2015–2017.
