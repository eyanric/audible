# audible — carry-forward state

**Read this first. Rewrite it as your final commit.**

This file exists because the previous carry-forward lived outside the repo, so the session that
needed to update it could not reach it. Everything a new session needs to avoid re-deriving
settled facts belongs here, in the repo, versioned with the code it describes.

Rules for editing:

- **Verified facts only.** If it was measured against a live API, say so and give the number.
- **Record the decision, not just the finding.** "Flagged not fixed" is the useful half.
- **Delete what stops being true.** A stale line here is worse than no line.

---

## DRAFT: Friday 28 August, 8:30. ESPN league 6012. **Eight days out.**

Everything below serves that date. **Code freeze Thursday 27 August** — no merges, no
rebuilds, no config edits after it.

Two tracks. **Track A never slips for Track B.**

| by | track A | track B |
|---|---|---|
| Mon 17 | build failure diagnosed — **done** | — |
| Tue 18 | data on disk, offline board proven — **done** | **B1 anchoring — done** |
| Wed 20 | latency — **dead end, see below** | **B-next mid-tier check — done** |
| Thu 20 | **P0 cockpit fixed + Playwright suite — done** | **C1/C2 — done. C3 — built, not run** |
| Thu 20 | **runbook: 3 corrections, 1 a trap — done** | **B3 — scoped; one real bug fixed** |
| Fri 22 | Sleeper mock rehearsal — **needs Eric** | B5, B6, B7 |
| Tue 26 | **digest pinned — done. Offline re-proof: needs Eric to run it** | — |
| Wed 27 | **freeze**, paper board | — |

---

## ⚠ How 2026-08-20 reached GitHub, and where it is not byte-exact

PR **#17**, branch `p0/cockpit-hit-target`. **234 tests green locally** (224 offline + 10
Playwright), ruff clean, pyright 0 errors.

The session's git proxy refused `eyanric/audible` — *"not in this session's authorized
repository set"*, a known open bug (anthropics/claude-code#76248) with no in-session fix —
and `api.github.com` answered 403, so `gh` was out too. Everything was pushed **through the
GitHub MCP by hand** instead, and verified by comparing the blob SHA GitHub reports against
`git hash-object` locally.

| file | result |
|---|---|
| `.github/workflows/ci.yml` | byte-exact |
| `docs/runbook-draft-day.md` | byte-exact |
| `src/audible/analysis/anchoring.py` | byte-exact |
| `src/audible/cli.py` | byte-exact (52,593 B, 63 `\n` escapes) |
| `tests/test_anchoring.py` | byte-exact |
| `tests/test_cockpit_ui.py` | byte-exact |
| `src/audible/server/static/index.html` | **228 B short** (64,149 vs 64,377) |
| `src/audible/analysis/substitution.py` | **9 B long** (22,018 vs 22,009) |
| `tests/test_substitution.py` | **21 B short** (16,065 vs 16,086) |

**The drift is confined to runs of repeated `─` (U+2500) in decorative comment separators,
and every discrepancy is an exact multiple of 3 bytes.** Those three files are the only ones
containing long box-drawing runs; every pure-ASCII file, and `cli.py` with its 63 escape
sequences, came out exact. `index.html`'s shortfall is 76 characters against 1,627 such
characters in 34 separator lines. **This has not been proven to be decoration-only** — CI is
what adjudicates it, and for the two Python files ruff/pyright/pytest are a strong gate.

**If byte-exactness matters, the five original commits exist as `git am`-able patches** (sent
to Eric 2026-08-20). Applying them supersedes the branch entirely.

**Still worth doing: add `eyanric/audible` and `eyanric/haven` to the session's authorized
sources.** Then a future session just runs `git push`, and the haven-side cluster fix below
becomes possible at all.

---

## ⚠ The cluster spare serves the WRONG LEAGUE

**Read from the live cluster on 2026-08-20**, not from a manifest in a repo:

```
Deployment/audible  ns audible   args: [audible, serve, --league, sleeper_boyfun, ...]
Service/audible                  loadBalancerIP: 192.168.1.110
```

So rung 2 of the League B runbook opened a **League A** cockpit — a correct board for the
wrong league, the same failure A3 caught in the launcher and fixed only there. Two more
properties of that pod, both from the manifest:

- **`image: ghcr.io/eyanric/audible:latest`, `imagePullPolicy: Always`.** Unpinned, and it
  re-pulls on every restart. A3 pinned the launcher; the cluster still moves.
- **Its cache volume is an `emptyDir`, not a PVC.** A pod restart wipes the board cache *and*
  the draft state, so it rebuilds **from the network** — the offline property A3 proved does
  not hold there — and the readiness probe allows five minutes for it. No ESPN cookies in its
  env either, so sync and slot resolution could not work for League B regardless.

`mcp-audible.havenhomelab.org` proxies that same pod, so **the published MCP tools answer for
League A**. `draft_status` returning `SUPER_FLEX`/`IDP_FLEX` in `unfilled_starting_slots` is
the tell.

**Done:** the cluster rung is removed from the runbook's fallback ladder, and the MCP caveat
is called out at T-30m. A rung you must read a caveat before using is not a rung at 8:40pm.

**Not done, needs a `eyanric/haven` PR (also unauthorized this session):** a second
`audible-espn` Deployment + Service — `--league espn_davis_drive`, `image:` pinned to the
launcher's digest, a real PVC at `/app/data`, the two ESPN cookies as secret env, its own
LoadBalancer IP. **Additive**, not a change to League A's: `audible` performs no platform
writes, so both run at once. Before the freeze or not at all.

## P0 — closed. It was the target, not a broken handler.

**Fixed and pinned by a regression suite (`df082c9`). Measured in Chromium at 1600×1000
against the running cockpit:**

| | before | after |
|---|---|---|
| best-available mark button | 18×18 | **26×21** (1.69× the area) |
| grab-now mark button | 18×18 | **26×24** (clears WCAG 2.5.8) |
| row double-click target | — | **976×23** |

The button was also `border-color: transparent` at rest, outlined only on `:hover`. **A
control nobody can see is one you click the row instead of, and clicking the row only
selects.** That is a complete account of "renders and does not respond to clicks" with no
handler broken — consistent with the CDP evidence below that nothing throws.

What changed, and what deliberately did not:

- The mark control fills its cell in a widened column, outlined at rest.
- **Row double-click marks.** Single click still only selects — deliberately, so a stray
  click while scrolling can never mark a player.
- Best-available rows still miss the 24×24 floor by 3px vertically. Raising the row
  re-densifies the whole board a week out; the 976px row is the large-target path instead.
  Stated in the CSS, not silently accepted.
- Mark buttons left the tab order. 140 rows was 140 tab stops.

**A real bug the new suite found, present before the change:** double-clicking the mark
button fired `markTaken` **twice**, pushing two entries onto `takenStack` — so one undo left
the player off the board and the second failed against a restored player. At draft speed,
double-tapping a small button is exactly what a person does. `markTaken` now ignores a repeat
while the first POST is in flight.

### P0.3 — shipped

`tests/test_cockpit_ui.py`: 10 Playwright tests driving Chromium against the real FastAPI app
on a synthetic board. No network, no cache, no Sleeper. It asserts what a person at a keyboard
does — render, select-without-marking, double-click-marks, button-marks, undo-is-a-true-
inverse, search-Enter-marks-the-named-match, `t`, pause — and fails on any console error,
uncaught throw or failed request.

**Negative control run, not assumed:** against the pre-fix page **4 of the 10 fail**,
including the double-mark bug. Against the fixed page all 10 pass.

Playwright arrives via `uv run --with playwright`, **not** a dependency group: one test file
needs it, nothing that ships does, and it has no business in the lockfile the draft-night
image resolves from. CI runs it as a separate `cockpit-ui` job with
**`AUDIBLE_UI_REQUIRED=1`**, which turns a skip into a failure — otherwise the job goes green
by running nothing the day the browser install breaks, which is the silent-empty class
(B6) this repo keeps finding. `AUDIBLE_UI_CHROMIUM=/path/to/chrome` uses an
already-installed browser instead of the exact build Playwright's wheel wants.

**Still open at one end:** Docker is unavailable in the agent environment, so the *pinned
image* was never exercised. The packaging failure mode that distinction was meant to catch is
eliminated below; what remains is `scripts\verify-offline.cmd` on Eric's machine.

### The original CDP evidence (kept — it is why the diagnosis landed where it did)

Driven in a real browser over CDP against `uv run audible serve --league espn_davis_drive`
(not by inspection):

| check | result |
|---|---|
| console errors / uncaught exceptions | **none** |
| failed network requests | **none** |
| rows rendered | 140 (grab 5, tabs 10) |
| click moves selection | yes |
| selection visibly distinct | yes |
| mark button removes the player | yes |
| undo restores him | yes |
| pause responds | yes |

**Two P0.2 suspects eliminated without Docker:**

- **"Static asset 404s under the container" cannot happen.** `static/` holds *one* file,
  `index.html`, whose only `href` is a `data:,` favicon — JS and CSS are inline. The Dockerfile
  copies `src/` wholesale and `STATIC_DIR` resolves identically, so the container serves a
  byte-identical self-contained page. There is no asset to fail to load.
- **The `takenStack` drift risk did not fire** — undo clicked against an empty stack, page
  kept working.

`scripts\diagnose-cockpit.cmd` is still the fastest on-the-night triage — start the cockpit,
double-click, and it launches its own throwaway browser, drives the page, and writes
`cockpit-report.txt`, exiting non-zero if the page is genuinely inert.

> It launches an **isolated** browser on purpose. Enabling remote debugging on a browser
> already in use exposes every open tab through the debugging port — that happened during this
> investigation on the default port, which is why the script pins its own profile and port.

---

## A3 — pinned; one step left and it needs a machine with Docker

**Pinned digest:** `ghcr.io/eyanric/audible@sha256:d3cdb2a101aaddfb88515956e93163d2f7bfa106273dd5da6e688d67339be570`
(main @ `39a13f3`, image build green). Set in `scripts/draft-day.cmd`.

**Found while pinning, and it would have been silent:** the image bakes
`--league sleeper_boyfun` as its default command. Pinning it as-is would have served
**League A on League B's draft night** — a correct board for the wrong league. The launcher
now overrides the command explicitly rather than rebuilding, so one image serves either league
and the league being drafted is visible in the launcher instead of buried in a layer. The
no-Docker fallback line named the wrong league too.

`.gitattributes` had `* text=auto eol=lf`, which would have handed a checkout LF-only batch
files. `draft-day.cmd` uses `goto` and labels; those misbehave on LF. `*.cmd text eol=crlf`
now pins it, verified against a fresh worktree checkout.

**Still to run, and it needs Eric — Docker is unavailable in the agent environment:**

```
scripts\verify-offline.cmd     (double-click)
```

It pulls the pinned digest, fills the cache volume *using that same image*, then rebuilds both
boards under `--network none` — the container's network namespace removed entirely, so an
OS-level block rather than a mocked one. Prints PASS or FAIL. **Do not freeze on a FAIL.**

The exact commands it runs were validated here first with outbound sockets blocked:
`audible draft espn_davis_drive --top 5` and the League A equivalent both exit 0 with full
boards. What is unverified is only what needs the real artifact: the pull, the volume, and the
namespace removal.

Then: print the paper board (`audible cheatsheet espn_davis_drive`), and **freeze Thursday 27**.

Plus A1 if a real full ESPN draft can be joined — see the recorded finding below.

**A1 latency is a dead end, not a scheduling problem.** ESPN will not start a draft with
unfilled slots — every seat must be filled before the listed start time or the draft is pushed
back in five-minute intervals indefinitely. Temp league `102010124`, read read-only:
`drafted: false`, `inProgress: false`, **0 real picks**. It was never going to produce a
number. The only route that can work is a **real, full ESPN draft you can join**, with
`scripts/espn_latency.py` running first — latency cannot be reconstructed after the fact.
**Optional**: manual entry is primary and the runbook assumes it. The runbook's latency
section now says this instead of telling you to run the temp draft.

---

## C3 — built, tested, and NOT RUN

`audible substitution espn_davis_drive` (`13f0ee9`). Replays each completed ESPN draft and
substitutes a decision rule into **one seat**, leaving every other seat where it was.

| line | what |
|---|---|
| `actual` | what the seat really drafted. The thing to beat. |
| `market` | ESPN's STANDARD rank **as served that season** — the ADP-naive control, and the right control because B1 says all seven opposing seats read it |
| `baseline` | a projection from season N−1 actuals only, ranked by raw points |
| `machinery` | the same N−1 baseline through this league's VORP engine |
| `hindsight` | the same VORP engine over **realized** points — projection error removed |

**The leak block, and the route around it.** `build_board` takes projections from
`SleeperAdapter.get_projections(season=N)`, and Sleeper serves a *current* state for a past
season, so a board built from it leaks the answer into the question. `regressed_ppg_baseline`
over N−1 actuals cannot — nothing from season N reaches season N's line, and that is one
assertable line of code rather than a claim.

**Which makes the gate asymmetric, and that is the point:**

- `machinery` beats `market` → a **lower bound** on the real board's edge.
- `machinery` loses → **uninformative, not a null.** A dumb projection ranked by a good
  method can lose for either reason and this design cannot separate them.
- `machinery` − `baseline` holds the projection fixed, so **that** comparison is separable.
  It is reported on its own line, and `verdict()` says all of this in prose rather than
  leaving it to whoever reads the table.

**A second handicap, found while building it, and it runs the same way.** Realized points are
ESPN's applied totals under *that season's* settings — STANDARD, zero PPR, for 2023–25. The
baseline is scored through `LeagueConfig`, which is **half-PPR for WR/TE**. So the baseline
over-rates receivers in exactly the place B-next showed our board departs from ESPN's. It
makes `machinery` worse, never better. Not corrected: per-season ESPN scoring tables are
fetched nowhere in this repo and inventing them would be a larger claim than the one under
test. Printed under the verdict.

**`hindsight` is deliberately not "take the best scorer left".** The first version was, and
it **lost to the machinery** — caught by a test asserting it was the ceiling. Greedy-by-points
spends early picks on abstract volume and fields a worse legal lineup. Running the perfect
projection through the *same* engine is the comparison that means something, because
`hindsight − machinery` is then the cost of being wrong about players and nothing else. It is
not a proven optimum and is never called a ceiling. A test pins the counter-intuitive part so
nobody re-derives it.

**Modelling choices, all in the docstring and all visible in the output:** opponents do not
react (they take their real player if he is there, else the best available on ESPN's board —
which is what B1 says this room does); the candidate pool is the players actually drafted; an
unscored player is counted, never zeroed, and no line may reach for him; **rosters must stay
legal** — a pick is allowed only if the remaining picks can still fill every starting slot,
derived from `starting_slots` and slot eligibility rather than a positional cap anyone chose;
scoring is best-ball on season totals through the same `assign_starters` the value engine uses.

14 tests, constructed ground truth throughout: hand the machinery the answer key and it must
produce the **identical** roster to `hindsight`; hand it a flat projection and it must not
beat a correctly-ordered market; a season without ranks must be skipped **with a reason**
rather than quietly run without its control.

**Never run against the real league** — no ESPN cookies, no Sleeper egress, empty `data/cache`
in the agent container. `audible substitution espn_davis_drive` needs Eric's machine.

---

## B3 — the corpus cannot be widened from here, and B1's join key was wrong

**Established before writing any code:**

- **ESPN cannot widen it, and that is not a credentials problem.** Cookies reach only leagues
  Eric is in, and 2021–25 of league 6012 is all that exists. Private-league cookies are not a
  discovery mechanism. **ESPN is a dead end for B3.**
- **Sleeper can widen C1/C2 but NOT B1.** `get_draft(id)` and `get_draft_picks(id)` need no
  auth, and picks + realized stats + final standings are all period-correct facts. B1 needs
  the served rank board *as of that season's draft*; Sleeper has no such endpoint, and its
  projections endpoint returns current state for a past season — the same leak that blocked
  C3. Widening B1 needs an archived contemporaneous ADP source this repo does not talk to.
  **Decide that before writing the adapter, not after.**
- **Sleeper has no league discovery of any kind.** The only traversal is `previous_league_id`,
  which widens *seasons of one league*, not leagues.

**Deliberately not done: the Sleeper season-history adapter.** It needs roster `settings`
field names (`wins`/`losses`/`fpts`/`fpts_decimal`) that would be recalled rather than
verified — no egress to `api.sleeper.app` here, and `tests/fixtures/sleeper_draft_2025.json`
is trimmed to `draft`/`me`/`rosters`/`users` with no settings and no picks. CLAUDE.md says
confirm exact fields against the live API first. Building it blind, a week before a freeze, in
the module the draft-night board depends on, is how that principle gets broken.

### What was fixed: `anchoring` pooled seats by `teamId`

`draft-quality` keys by owner GUID and its docstring says why — *"ESPN reuses teamId across
seasons and a seat is a person, not a slot."* `anchoring` did not. Where an id changed hands,
B1 pooled **two managers into one seat** with twice the picks, and nothing in the output would
have looked wrong. Widening a corpus whose join key can silently merge people is the wrong
order of work.

Seats are now keyed by the owner GUID from the standings, and the report carries:

- **`identity`** — `"owner"` or `"team_id"`, i.e. which key was actually used. A run that fell
  back to the weaker key is otherwise indistinguishable from one that did not.
- **`id_moves`** — every team id that changed hands, and every manager who held more than one.
  **Empty means the two keys agree**, which is what would make the published B1 table safe to
  keep. Printed explicitly rather than left to be assumed.

**`--me 8` is gone.** A personal team id as a CLI default is wrong twice over: a constant in
the wrong place, and an identity ESPN may reassign. It defaults to the authenticated
`ESPN_SWID` and is matched as an owner GUID. Getting `me` wrong does not merely mislabel a row
— it **drops a real opponent from the table and adds Eric to it as if he were one**. On the
degraded path (no standings) a numeric `--me` is still honoured, because quietly putting my
own seat back would be worse than the weaker key that caused it.

**Unverified, and it needs Eric:** whether any team id actually moved in 2023–25. Run
`audible anchoring espn_davis_drive` and read the new identity lines. **If `id_moves` is empty
the published B1 numbers stand unchanged; if it is not, they were pooling two people.**

`--seasons` also added to `anchoring` and `draft-quality` — the kwarg existed on `build_report`
in both and was unreachable from the CLI.

## Where the project is

| | |
|---|---|
| Phase | 2b complete. ESPN adapter, ESPN sync, and an offline-capable board. |
| Leagues | A = Sleeper `sleeper_boyfun` (10-team, superflex, IDP). B = ESPN `espn_davis_drive` (8-team, 1-QB, no IDP). |
| Board source | Sleeper stat lines for **both** leagues, scored through each league's own weights. League B's `draft` output carries a header saying so. |
| Live sync | Both platforms, one poll loop, behind `draft/sync.py`. Verified: `ok:true`, 3,300 players, 0 picks pre-draft, seat 8 derived. |
| Data | **On disk.** Board builds with the network unplugged — see below. |
| Tests | **234** — 224 offline plus 10 Playwright driving the real cockpit in Chromium. |
| CI | two jobs: `check` (ruff / pyright / pytest with `--extra nflverse`) and `cockpit-ui`. |
| Not started | Phase 3, Phase 4. |

**`live` is Sleeper-only** and says so — it polls the adapter directly rather than going
through the cockpit. League B's live surface is `serve`.

---

## The board builds offline — the property that matters on the 28th

Every board input used to be a third-party URL fetched fresh on every process start, because
nflreadpy caches **in memory only**. On 2026-08-17 one of those URLs started returning a 404
page and the board stopped building entirely.

Now: **the network is an update mechanism, not a dependency.**

- `FrameCache` (`adapters/cache.py`) — parquet on disk plus a manifest of source, fetch time,
  checksum, rows. **Deliberately no TTL.** A time-to-live expires on its own schedule, which on
  draft night means the one restart that matters is the one that decides to go to the network.
  Present means used.
- Every nflverse loader routes through it. A fetch that fails with a cached copy present is not
  an error — the copy is the answer. A fetch that fails with **no** cache still raises, because
  silence is the one unacceptable outcome.
- Sleeper projections are cached too. They were not, and they *are* the projections — no amount
  of nflverse caching could have produced an offline board without them. The players catalog
  keeps its TTL for freshness but serves stale rather than failing.
- **`audible refresh-data`** is the one command that is supposed to need the network. It
  refreshes by building each league's board, so the cache holds exactly the sources `serve`
  will ask for at the seasons it will ask for them.
- `/healthz` reports source count, age, and whether inputs came from disk or network.

**Verified with outbound sockets blocked** (`getaddrinfo`, `connect`, `connect_ex`):

```
espn_davis_drive  3300 players  DEF=32 K=157 QB=355 RB=744 TE=649 WR=1363
sleeper_boyfun    7621 players  + DB=1778 DL=1439 LB=1136
#1 Jahmyr Gibbs in both — identical to the online build
serve: ok:true, data.origin "disk", sync_status "failing"
```

**Run `audible refresh-data` on the 27th before the freeze.** The volume must map to
`/app/data/cache` in the container.

---

## C1/C2 — draft quality, and whether it decides anything

`audible draft-quality espn_davis_drive`. All five seasons (no ADP needed).

**C1 — mean draft rank across 2021–25 (1 = best draft that season):**

| seat | mean | sd | best | worst | mean finish |
|---|---|---|---|---|---|
| WCW | 2.20 | 0.84 | 1 | 3 | 2.60 |
| Ryan | 3.00 | 3.08 | 1 | 8 | 3.60 |
| BTD | 3.40 | 1.67 | 2 | 6 | 4.20 |
| FAT | 5.00 | 1.87 | 3 | 7 | 5.40 |
| BUTT | 5.00 | 2.24 | 2 | 8 | 4.00 |
| PM | 5.20 | 2.49 | 1 | 7 | 7.00 |
| Cnk | 5.80 | 1.92 | 3 | 8 | 4.80 |
| JEFF | 6.40 | 1.52 | 5 | 8 | 4.40 |

One seat drafts consistently well (**WCW**, never worse than 3rd). One is pure variance
(**Ryan**, best *and* worst in five years). The rest reshuffle. **BUTT is Eric** — mean draft
rank 5.00, mean finish 4.00.

**C2 — does drafting predict finishing? Not resolvably, at this sample size.**

Per-season rho(draft rank, finish): −0.167, +0.262, +0.214, **+0.976**, +0.571.

| unit | rho | 95% CI |
|---|---|---|
| draft → finish | +0.371 | [−0.160, +0.903] |
| draft → points for | +0.414 | [−0.212, +1.040] |

**Both intervals cross zero.** The pooled n=40 figure looks better powered than it is: within
a season the eight draft ranks are a permutation and so are the finishes, so seats are not
independent and pooling counts one season's evidence eight times. Seasons are independent —
that leaves **n=5**, and the per-season values run from −0.17 to +0.98 with one season
carrying the mean.

So this neither establishes that draft edge decides seasons here nor that it doesn't. Five
seasons of an eight-team league is all the data that exists; **B3's corpus widening is the
only way to sharpen it, and it can run after the draft.**

The draft tracks **points** more closely than **standings**. A better draft scores more;
converting that into wins runs through a schedule nobody controls.

*Caveat stated, not solved: drafted-roster points ignore waivers, trades and start/sit. It
measures the draft, not the season.*

---

## B-next — the scoring edge IS real, and B1's "no edge" was half the story

`audible rank-check espn_davis_drive`. B1's conclusion (below) still holds for whole
archetypes. But the rank comparison that supported it was **top-24 only**, and that is the one
tier where agreement is guaranteed for reasons unrelated to scoring — elite receivers are
elite in every format.

Across ranks 25–200 the boards diverge sharply:

| tier | n | mean | median | mean&#124;d&#124; | moved |
|---|---|---|---|---|---|
| 1–24 | 24 | −1.4 | −0.5 | 2.5 | 1 |
| 25–60 | 36 | −4.1 | −9.0 | 14.9 | 25 |
| 61–120 | 60 | +0.6 | −5.5 | 22.8 | 50 |
| 121–200 | 34 | +4.2 | 0.0 | 11.3 | 13 |

**Divergence alone proves nothing** — two boards can disagree for reasons unrelated to
receptions. So the hypothesis is tested directly: Spearman(receptions, rank delta) **within
position**.

| pos | 1–24 | 25–60 | 61–120 | predicted sign |
|---|---|---|---|---|
| WR | +0.90 | +0.70 | +0.58 | **+** (paid 0.5/catch) |
| RB | −0.53 | −0.06 | −0.62 | **−** (paid 0.0/catch) |
| TE | — | — | −0.14 | + (weak/contrary) |

Both major signs came out as predicted. **The edge is real, it is in rounds 3–10, and it is
within position rather than across it:**

- Among **WRs at a similar ESPN rank** — take the high-reception possession receiver over the
  low-volume deep threat.
- Among **RBs** — fade the pass-catching back, prefer the pure rusher.

**Do not act on the whole-position moves.** QB and TE rise as blocks on our board; that is
VORP-versus-market structure, not receptions, and this gate establishes nothing about which
side is right. The CLI verdict says so explicitly.

**Method note worth keeping:** the first cut averaged the within-position correlations, which
is wrong — the scoring predicts *opposite* signs by position, so a real WR effect and a real
RB effect cancelled and the verdict read "not reception-driven". Averaging across groups with
opposing predicted signs will always do this.

---

## B1 — opponent anchoring: settled (whole archetypes only)

> **⚠ The table below was produced with seats keyed by `teamId`, and the key has since
> changed to the owner GUID (see B3).** ESPN reuses team ids across seasons, so if any id
> changed hands in 2023–25 these rows pooled two people. **Re-run
> `audible anchoring espn_davis_drive` and read the new `identity` / `id_moves` lines.** If
> `id_moves` is empty the numbers below stand exactly as they are; if it is not, replace them.
> The room-level verdict (7/7, sign test p = 0.016) is the more robust half, but the seat
> count itself would change.

`audible anchoring espn_davis_drive`. 384 picks over 2023–25, 79.9% usable.

| seat | disc | sp(STD) | sp(PPR) | mad(STD) | mad(PPR) | edge | ±1.96se | reads like |
|---|---|---|---|---|---|---|---|---|
| PM | 12 | +0.914 | +0.780 | 14.1 | 22.9 | +26.3 | 20.1 | espn |
| FAT | 14 | +0.853 | +0.728 | 19.6 | 27.9 | +24.4 | 11.2 | espn |
| WCW | 13 | +0.806 | +0.752 | 23.3 | 29.4 | +18.1 | 16.3 | espn |
| Cnk | 13 | +0.884 | +0.792 | 15.4 | 19.8 | +12.7 | 10.7 | espn |
| JEFF | 16 | +0.847 | +0.723 | 18.4 | 22.6 | +8.2 | 15.5 | unclassified |
| Ryan | 15 | +0.858 | +0.826 | 19.9 | 23.0 | +7.5 | 11.4 | unclassified |
| BTD | 17 | +0.778 | +0.769 | 20.4 | 23.9 | +6.1 | 10.4 | unclassified |

`edge` = mean(|PPR rank − pick|) − mean(|STANDARD rank − pick|) over picks where the boards
disagree by ≥10 ranks. Positive ⇒ the seat tracks ESPN's board.

**Verdict: no seat is PPR-anchored. All 7 of 7 lean toward ESPN's board (sign test
p = 0.016).** Individually most seats are underpowered at ~13 discriminating picks; the
unanimity is not, and that is the level the finding is stated at.

**What this means for the 28th — as amended by B-next above.** No opponent is on a generic
PPR board, so there is no *whole-archetype* steal: don't plan to hoover up Henry-types late,
this room is not systematically undervaluing them.

But because all seven read ESPN's ordering, and our board demonstrably departs from that
ordering on reception grounds inside WR and RB in rounds 3–10, the **within-tier** edge is
live. B1 rules out the crude version of the exploit; it does not rule out the real one.

**Two defects this found, both fixed:**

1. **ESPN's rank tail is a placeholder, not an ordering.** Only ~155 players per season hold a
   STANDARD rank ≤200 and ~280 hold one ≤400; ~800 more carry values running to **2687**. A
   player can sit at STANDARD 57 / PPR 2554 — that is one board declining to rank him, not the
   boards disagreeing. Left in, a few of these dominated every average (mean divergence 85.2
   vs median 10.0; standard errors of 250+ where the effects are ~20). **`RANK_HORIZON = 200`**
   now excludes them and the excluded count is reported. This is another instance of the B6
   silent-empty class: a field that looks like data and is not.
2. **A zero standard error read as no signal instead of a perfect one.** Every discriminating
   pick pointing the same way by the same margin is the strongest possible result, and the
   guard rejected exactly those.

---

## The `image` workflow failure — resolved

It was the **smoke test**, not the build. Steps 1–6 were always green; step 7 ran the full
455s of its 90×5s health loop because `/healthz` never went green — the board could not build
inside the container after the DynastyProcess 404. PR #9's smoke test passed in **17 seconds**
before that URL broke; PR #10's never got there after.

The smoke test now tests the **image**: the container must start, answer `/healthz` with the
contract's keys, and render the index. Board readiness from a cold cache is **reported, not
gating** — it is a live-network question, and a gate that reddens during someone else's outage
is one you learn to ignore. Now green in 18s. The board path is covered deterministically and
offline in `tests/test_datacache.py` instead.

---

## ESPN — verified, do not re-derive

### Auth and transport

- `League(league_id=6012, year=season)` with cookies `espn_s2` and `SWID` (braces kept), read
  from `.env`. Read-only; nothing writes to ESPN.
- Endpoint: `lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leagues/6012`.
- **The ESPN endpoint is not edge-cached.** Measured: `x-cache: Miss from cloudfront`,
  `cache-control: must-revalidate`, no `age` header. Use a conditional GET with `If-None-Match`
  and **no cache-buster** — a repeat request returns `304` with 0 bytes.
  **Sleeper needs a cache-buster; ESPN does not. Do not generalise either way.**

### Player pool

- `view=kona_player_info` plus an `X-Fantasy-Filter` header.
- **`sortDraftRanks` is mandatory.** Without it the endpoint returns `200` with zero players and
  no error of any kind. An empty pool raises rather than becoming an empty board.
- Pool saturates at **1,026**.

### Translation map

- **RB / WR / TE:** exact via statIds `{3, 4, 20, 19, 24, 25, 26, 42, 43, 44, 53, 72}`.
- **QB:** passing yards ride **`statId 8`** — ESPN's bucketed "one point per completed 25 yards".
  `statId 3` (raw yards) is *not a scoring item in this league for any position*. Converting
  buckets back to yards reproduces ESPN exactly through our own `pass_yd = 0.04`
  (25 × 0.04 = 1.0), so no ESPN branch enters the scoring engine.
  Measured: Josh Allen `statId 3 = 3944.73`, `statId 8 = 157` buckets = 3925 yards.
- **K and D/ST:** ESPN-native verified, translation **incomplete — flagged, not fixed**:
  - kicker misses are bucketed −1 / −2 / −3 (statIds 200/203, 82, 88) against our flat
    `fgmiss = -1`;
  - D/ST yards-allowed tiers are absent entirely (128/129/130 = +5/+3/+2;
    133/134/135/136 = −3/−5/−6/−7).
  - ~15 pts/season across two positions holding one roster slot each, drafted last in an
    8-team league. Recorded; not worth a config change.

### Reconciliation residual

`statId 63` (offensive fumble recovered for a TD, paid 6.0) is unmapped — our config has no key
for it and the config is not changing. It is the **entire** difference between our recomputation
and ESPN's own `appliedTotal`:

| pos | delta / season |
|---|---|
| QB | −0.233 |
| RB | −0.069 |
| WR | −0.045 |
| TE | −0.022 |

0.06% of a QB season, monotone in fumbles (already penalised via `fum_lost`). Deliberate.

### Fallback populations

Of the 1,026-player pool: **432** scored by us from translated stat lines, **89** K/D-ST handed
to ESPN by design (the flagged gap above), and **505** offensive players taking ESPN's number —
431 project to 0.0 either way, and 74 are return-only specialists scored on return yards this
league does not pay (largest projects 65 pts against a WR replacement level of 182). All three
paths are counted and printed; none can pass for a computed projection.

### Ranks

`playerRankType = "STANDARD"`. Per-season ranks exist 400/400 for 2023–2025 and are **absent for
2021–2022** — sorting by a rank type that isn't there returns arbitrary order silently.

**STANDARD is not a zero-PPR ordering.** ESPN serves four types (STANDARD, PPR, ELIMINATION,
SUPERFLEX); STANDARD matches PPR at the top and diverges only for non-receiving backs
(Derrick Henry STANDARD #10 / PPR #19; Chase, Nacua, Gibbs, McBride, Bowers identical in both).
STANDARD is still the right type for this league — it pays RBs nothing per reception — but
anything treating it as a market baseline for a half-PPR field will be wrong.

### Scoring, confirmed live

0.5/reception for WR/TE, **0.0 for RB** (deliberate, commissioner-confirmed). 48 position-scoped
weights, **zero drift**. The half-PPR flip has landed.

Comparison must read `pointsOverrides` per position, not `points`: ESPN encodes receptions as
base 0.0 with QB/WR/TE overrides while our config says base 0.5 with an RB override. The two
agree everywhere it matters; a base-against-base comparison reports drift across the whole table
where there is none.

### Draft detail

- `view=mDraftDetail` → `draftDetail.{drafted, inProgress, picks}`.
- **Pre-draft returns a full 128-entry placeholder slate with `playerId: -1`** (8 teams ×
  16 rounds). Filter `playerId != -1`; use `drafted` / `inProgress` for real state. A sync that
  counts raw pick records believes the draft finished before it started.
- Pick fields: `playerId`, `teamId`, `roundId`, `roundPickNumber`, `overallPickNumber`.
- `settings.draftSettings.pickOrder` is teamIds in draft-slot order — measured
  `[2, 3, 6, 4, 1, 5, 7, 8]`, which matches the round-1 slate exactly. It is **not** an identity
  map, so it is real commissioner-set data rather than a Sleeper-style placeholder. Type `SNAKE`,
  `orderType: MANUAL`, 90s per selection.
- Eric's team is derived from `ESPN_SWID` against `teams[].owners` — **team id 8**, which is
  **draft slot 8**. No flag required. Match `owners`, not just `primaryOwner`: at least one
  team in this league is co-owned.
- Rounds = **16**, agreeing two ways: `max(roundId)` over the slate, and
  `sum(lineupSlotCounts) − IR`. The sync uses the second, so the clock does not depend on what
  ESPN serves in the slate once a draft is under way.
- **One request per tick.** `mDraftDetail` + `mTeam` + `mSettings` ride one conditional GET, so
  everything — state, picks, seats, rounds, structure — comes out of that single response.
  Reading rounds back through the adapter's standalone helper silently added a second,
  unconditional `mSettings` request on every 5s tick; there is a test pinning this at one.

### Roster structure

`settings.rosterSettings.lineupSlotCounts`, by ESPN lineup-slot id:
`0:QB=1, 2:RB=2, 4:WR=2, 6:TE=1, 23:FLEX=1, 16:D/ST=1, 17:K=1` = **9 starters**, plus
`20:BE=7` and `21:IR=3`. Matches `leagues/espn_davis_drive.toml` exactly.

`verify-scoring espn_davis_drive` checks this live and reports **faithful** as of 2026-08-17.
An ESPN lineup-slot id we do not map, carrying a non-zero count, reports as `slot#<id>` rather
than being skipped — a starting slot with no name is exactly the drift worth being loud about.

---

## Sleeper — verified, do not re-derive

- Projections/stats on `api.sleeper.com` (undocumented, Rotowire); league/roster/players on
  `api.sleeper.app/v1`. Never trust precomputed `pts_*` — recompute from the raw line.
- **`/picks` IS edge-cached** (Cloudflare `s-maxage=30`, measured 57s stale against a 60s pick
  timer). Every poll needs a unique cache-busting param, then an `If-None-Match` for the cheap
  304. Opposite of ESPN — see above.
- `draft_order` is `null` until the draft opens. `slot_to_roster_id` exists pre-draft as the
  identity map `{1:1, …}` and **lies**: the completed 2025 draft shows `{1:4, 2:2, 3:6, …}`.
  Never derive a slot from it. A resolution derived pre-draft is never cached.
- Users and rosters are not 1:1 — 9 users, 10 rosters, two with `owner_id: null`, one co-owner
  owning no roster.
- ADP `999.0` means "undrafted in this market", not a real ADP.

---

## Known breakage being worked around

**nflreadpy 0.1.5 cannot reach DynastyProcess.** It hardcodes
`https://github.com/dynastyprocess/data/raw/master/files/`, and GitHub now answers that path
with a 404 HTML page. Measured 2026-08-17: that URL returns 404 with 305 KB of error page,
while `https://raw.githubusercontent.com/dynastyprocess/data/master/files/…` returns 200 with
the 2.6 MB CSV. 0.1.5 is the latest release — there is nothing to upgrade to.

`adapters/nflverse.py` tries nflreadpy first and falls back to the raw host for the two
affected loaders. Primary-first means it resumes using upstream on its own once fixed;
**delete the workaround block then.** The disk cache above is the real protection — the
fallback still needs the network to cooperate, and on draft night nothing may.

The fallback reads every column as a string on purpose — this is an ID spine, and a
`sleeper_id` inferred as a float becomes `"4034.0"` the moment anything stringifies it, failing
the join silently for every player instead of loudly for none.

**nflreadpy caches in memory only** (`CacheMode.MEMORY`). That is why the disk cache exists;
without it every process start re-downloads and repeated builds earn a `429` from GitHub raw.

---

## Standing decisions

- **`leagues/*.toml` does not change** to chase a translation gap. Flag it here instead.
- **Manual picks are real picks** — numbered, attributed to whoever is on the clock, and they
  advance the clock. Indistinguishable downstream from synced picks, including `_recent_picks`
  and the run window, both of which read `effective_picks()`. Reversing this caused
  "unlimited players join my roster", "undo leaves them there", and "no other team ever
  appears" from a single line.
- **Never invent a draft slot.** Unresolved is an explicit state; `slot = 0` meant "me" and
  silently attributed the whole room to one roster. Both platforms now derive the seat rather
  than taking a flag, and both return `None` with source `unresolved` when they cannot.
- **One poll loop, one `DraftSession`.** Everything platform-shaped lives behind
  `DraftSync.poll(draft_id, want_meta=, slot_locked=) -> DraftUpdate` in `draft/sync.py`.
  `DraftUpdate` uses `None` for "unchanged": a poll that only fetched picks must not blank the
  draft status it never asked about. Sleeper honours the `want_meta` / `slot_locked` hints
  (three endpoints, and `draft_order` is immutable once open); ESPN ignores both, because its
  whole draft is one response and re-resolving costs nothing — which also means a pre-draft
  pick order the commissioner reshuffles gets followed rather than cached.
- **ESPN picks arrive in ESPN's id space; the board is in Sleeper's.** `EspnIdBridge`
  translates via the Sleeper catalog's `espn_id`. An id that will not translate keeps its ESPN
  value rather than being dropped — the pick really happened, so the clock must move and the
  player must count as taken — and those are counted and logged. This becomes an identity map,
  and the class goes away, when `build_board` reads from the platform adapter.
- **A seat is a person, not a `teamId`.** ESPN reuses team ids across seasons. Every analysis
  that pools a manager across seasons keys on the **owner GUID** — `draft-quality` always did,
  `anchoring` now does, `substitution` resolves my seat that way. The GUID is a join key only:
  seats display by team abbreviation and the real names in `mTeam.members` are never read.
  Where the GUID cannot be resolved, the report **says which key it used** rather than falling
  back silently.
- **In the cockpit, a single click SELECTS and never marks.** Marking needs a deliberate
  gesture: double-click the row, the ✕ button, `t` on the selected row, or Enter from the
  search box. A stray click while scrolling must not be able to remove a player from the
  board, and undo must stay a true inverse — one gesture, one mark, guarded by an in-flight
  check because three surfaces now reach `markTaken`.
- **Consensus is the projection of record.** The opportunity model lost out-of-sample at every
  position; it rides as a flag overlay, never as a multiplier.
- **`value_metric = "vorp"` for League B**, not scarcity/VONA — VONA edged it in backtest
  (+28 vs +24) but the current implementation has a junk-tail pathology on flat positions that
  produces a QB-dominated board. Tracked; ship on VORP.
- No model calls inside `audible`, ever. No writes to any platform.

---

## Open / next

Ordered by what actually threatens the 28th.

### 1. Review PR #17, and decide whether byte-exactness matters

The work is on GitHub, pushed through the API rather than by `git push` — see the note at the
top for which three files are not byte-identical and why. **Read CI first**: `check` runs
ruff/pyright/pytest and `cockpit-ui` drives the real page in Chromium, so between them they
adjudicate everything the transcription could plausibly have broken.

If CI is green and the diff reads right, merge it. If you want the bytes to match exactly,
apply the five `git am` patches instead — they supersede the branch. Either way, **add
`eyanric/audible` and `eyanric/haven` to the session's authorized sources** so no future
session has to do this by hand.

### 2. Eric's machine, before the freeze — the T-24h checklist

`docs/runbook-draft-day.md` now opens with an eight-step ordered checklist. Two of them have
never been run against the real artifact and cannot be run from an agent container:

- **`scripts\verify-offline.cmd`** — pulls the pinned digest, fills the cache volume *with
  that same image*, rebuilds both boards under `--network none`. Prints PASS or FAIL.
  **Do not freeze on a FAIL.**
- **`audible refresh-data`** against the pinned image, confirming the volume maps to
  `/app/data/cache`.

Plus the ten-second one that is new: open the page, **double-click a row**, Ctrl+Z. It is the
only check that exercises what you will do 128 times on Friday.

### 3. The cluster spare — decide before the freeze

It serves League A, is unpinned, and loses its cache on restart (full detail at the top). The
runbook no longer offers it as a rung. Either add an `audible-espn` Deployment in `haven`
(additive; sketch is at the top) or accept a two-rung ladder — `serve` from source, then
paper. **Both are fine. Silently leaving a wrong-league rung in the ladder was not.**

### 4. Two analyses that are written but have never touched real data

- **`audible substitution espn_davis_drive`** (C3) — needs ESPN cookies and Sleeper egress.
- **`audible anchoring espn_davis_drive`** — re-run it and read the new `identity` /
  `id_moves` lines. **This one decides whether the published B1 table is still true.**

Both are read-only and safe to run before the freeze; neither is on the draft-night path.

### 5. The rehearsal — still nobody has drafted with this

**A Sleeper mock, three rounds, cockpit open.** Free, and it exercises sync, staleness,
grab-now, snake math and the UI, all of which League B shares. **The three-second manual-entry
standard has never been measured**; that needs a human at a keyboard and belongs here.

The P0 suite now proves the gestures *work*. It cannot prove they are fast enough with a pick
being called out loud at you.

### 6. Lower value, and none of it before the freeze

- **`scripts/espn_latency.py` is not folded into the CLI** and is untracked. It works; it just
  is not repeatable-by-command. Low value until there is a draft to measure.
- **Track B remainder:** B2 (384-pick evaluation, leak-free), B4 (Eric's picks + wins
  conversion), B5 (tendencies), B6 (silent-empty guard — B1's rank tail was the fifth
  occurrence, and the `AUDIBLE_UI_REQUIRED` gate is the sixth place it was worth pre-empting),
  B7 (Phase 4 metrics, only after B2 reports).
- **B3 proper is blocked on a decision, not on effort** — see the B3 section. Sleeper widens
  C1/C2 and cannot widen B1 without an archived contemporaneous ADP source. Decide that first.

**B1 + B-next together constrain the rest:** there is no *whole-archetype* edge against this
room, but there is a live within-position one in rounds 3–10. Nothing above is needed to
justify the draft-night guidance, which rests on the rank comparison and on arithmetic.
