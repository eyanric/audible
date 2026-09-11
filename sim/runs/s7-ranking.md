# S7 — one ranking system, validated weekly

Written so a later session needs neither the PR nor the handoff. Every number here has a
committed script and a committed output behind it; the script name is given beside each.

---

## The result, in one paragraph

The weekly sample did not resolve what six seasonal observations could not, because there was
probably nothing there to resolve. Twenty-four terms were tested in three leagues — sixteen
signals the handoff listed as prior nulls, plus eight new metrics built for this session — over
118 weekly scopes and seven seasons. That produced 336 hypothesis tests and 20 hits at p ≤ 0.05
against **16.4 expected under a pure null**. Seven measurements earned a verdict of `RESOLVES`,
across **seven distinct terms — not one replicated in a second league**. The incumbent draft
board stands.

One lead survives: `inj_status` at wide receiver, the only (term, place) pair in 336 tests that
hit in two leagues. It is pre-registered for 2026 with a direction and a size.

---

## What was measured, and on what

- **Projections**: `sim/data/ffa_corpus/`, the FFAnalytics weekly `raw` exports landed by
  `audible#90` and `audible#91`. 612 files, gitignored. `raw`, never `proj` — a `proj` export is
  scored under the FFAnalytics default league and capped at 36 QB per season, which cannot serve a
  10-team SUPERFLEX.
- **Outcomes**: `player_stats_{2019..2025}.parquet`, scored under each league's own rulebook.
- **Metric**: round-weighted rank error, symmetric indexing, settled in `audible#85`/`#88`.
- **Scale**: VORP on both sides, which is what the draft board ships. Raw points reported beside
  it; see "the SUPERFLEX finding" below.

**The window is 118 scopes, not the 169 the corpus offers.** The outcome side binds:
`player_stats` is pinned for 2019–2025 only, so 51 weekly projection files sit on disk with no
pinned outcome and are not scored. Nothing is substituted. Scored player-weeks are 15,104 /
18,880 / 22,420 for green_hope / danger_zone / boyfun — the *candidate* pool is 36,201, and an
earlier version of this report published the candidate count as though it were the sample.

---

## Phase 1 — the harness, and two retractions

`sim/s7_weekly.py`, `sim/s7_phase1.py`, output `sim/runs/s7-phase1.txt`, gates
`sim/test_g_s7.py`, mutation sweep `sim/s7_mutate.py` → `sim/runs/s7-mutate.txt`.

FFA weekly board, vorp scale, symmetric indexing:

```
green_hope   34.906  sd 4.279     floor 53.184
danger_zone  41.288  sd 4.660     floor 66.387
boyfun       48.502  sd 5.228     floor 79.562
```

### RETRACTED: "the weekly and seasonal floors are the same" is arithmetic, not a finding

`rank._realised_order` replaces realised values with within-pool ranks and `rank._weights` reads
only the two ranks, so a shuffled board's score is a function of `pool_size` and `teams` **and of
nothing else**. `s7_weekly.permutation_floor` reproduces all three leagues' floors from synthetic
ids with no football at all: 53.084 / 66.350 / 79.582. The weekly and seasonal floors agree
because both score 128 / 160 / 190-player pools at 8 / 10 / 10 teams. They would agree whichever
problem were harder. The first version of this phase inferred difficulty from that agreement and
was wrong.

What the shuffle floor is good for is a bar on the *metric*: a shuffled real board must land where
the synthetic one does, or the metric is reading something other than the two ranks.

### RETRACTED: G1's perfect-board check is a tautology

The perfect board is sorted by the same key `rank._realised_order` uses, so it reads 0.000000
against any outcome dict at all — demonstrated against uniform random numbers. The units invariant
is about the **perfect board in the wrong unit**, which must cost something: 38.363 / 27.814 /
6.776. The old chance bar was `chance < rwre + 1.0` where `rwre` is always exactly 0.

### The replacement gate fired, and finding out why produced a result

The first replacement asserted that the FFA board on the matched scale beats the FFA board on the
wrong scale. That **failed** on sleeper_boyfun 2024 wk8: points-ordering scores 51.413 against the
vorp outcome where vorp-ordering scores 52.163. In a 10-team SUPERFLEX the VORP transform makes
the weekly ranking *worse*. `rank.vorp_values` already records `compute_vorp`'s `rostered_counts`
as known wrong at QB. That is an empirical finding, not an invariant, so it is reported rather
than gated.

### Three measurement defects, all of which moved published numbers

1. `realised_week` paid neither return yards, return touchdowns nor fumble-recovery touchdowns
   while the seasonal side pays all three — 28 offensive players and 68.0 points in one week of
   one league, up to 13.0 for a single returner.
2. The realised VORP grouped players by their **nflverse** position while the per-position metric
   grouped them by their **FFA** position. `00-0033357` is an FFA quarterback and an nflverse tight
   end; alone he produced 11 QB rank flips in 2021 wk17. 17 of 118 scopes were affected.
3. The per-position figures are **scale-blind**. VORP is a within-position monotone shift, so it
   cannot reorder anyone inside a position — bitwise identical across scales in 101 of 118 scopes.
   This is now gated, so no later phase can read them as scale-specific.

### Coverage gap, previously undocumented

The regular season has been **18 weeks since 2021** and the corpus stops at week 17. For 2021–2025
one week of realised production per season has no projection and can never be scored, and a
seasonal per-game outcome includes production a weekly aggregate built from this corpus cannot.

---

## Phase 2 — sixteen prior nulls, re-adjudicated weekly

`sim/s7_phase2.py`, outputs `sim/runs/s7-phase2-<league>.{txt,jsonl}`.

### The design was wrong the first time, and the first run was killed at 34 of 51 records

It fixed the treatment strength at λ = 0.10 and adjudicated on "beats the floor". At a fixed
strength **every** term measures negative — a random term at λ 0.10 costs about −0.55 RWRE,
because multiplying a good ranking by (1 + 0.1·z) with noise for z can only add noise. So "beats
the floor" would have resolved terms that leave the board *worse than not touching it*.
`snap_share` read −0.3051 board-wide with p 0.024 and was one commit from being published as a
resolution.

Strength is now selected **leave-one-season-out** over a grid containing 0.0, which is what
`signals.loso` does seasonally. A term whose best strength is nothing selects nothing and
contributes exactly 0.000; the floor goes through the identical selection, so the p tests against
*selection noise* rather than against zero. In 31 of 72 measurements the selection chose λ = 0 in
every fold — the machinery saying "do not use this term".

`MATERIAL = 0.10 RWRE` is pre-registered separately. Out-of-sample selection makes floor draws
cluster on exactly 0.000, so any positive effect however tiny reads p = 0.0244 — a correct
reference-set test and a useless headline. Statistical and practical significance are two
different words and are never merged.

### Two of the sixteen had never been tested at all

- **air-yards share** — `prior_ay_share` has sat in `residual.prior_facts` since S3 and no signal
  ever read it. Not resolved, not null: absent.
- **route participation** — no pinned file holds routes run. Built as a pass-play participation
  proxy from `participation_s4.offense_players` and named for what it measures.
  **The pin has a schema break at 2023**: before it, a non-pass play carries `route = null`; from
  2023 it carries `route = ""`. The obvious filter selects 17,926 of 47,875 plays in 2018 and
  46,168 of 46,168 in 2023 — pass-play participation in one half of the window and plain snap
  share in the other, silently. Non-empty is the filter that means one thing across it.

### Two signals were coupled to the ESPN arm

`signals.signal_values` builds `availability` and `adp_gap` over `arms.load("espn", …)`, and the
espn arm refuses 2023 outright. Asking it for a 2023 value raised `PreflightError` and
`availability` read **0% coverage that season** — a missing measurement wearing a null's clothes.
Both are rebuilt over the FFA universe by the same construction.

### G5: `availability` now actually applies

One board-scope cell, `sd` 0.649, not the 8.95e-16 of floating-point residue `audible#87`
published. Its per-position effect is **exactly +0.0000** at all four positions, reproducing that
session's finding rather than citing it: a position-level constant provably cannot reorder a
position. Positions where a term holds one distinct value are now reported as *structurally zero*
and no p is printed for them, because the floor at those positions is not zero and comparing the
two produces a p for a quantity the treatment could never move.

---

## Phase 3 — new metrics

`sim/s7_metrics.py`, `sim/s7_phase3.py`, outputs `sim/runs/s7-phase3-<league>.{txt,jsonl}`.

The board reads one input and discards the rest of the file it was built from. Every weekly FFA
export carries, per player and unused: a standard deviation for every stat, an `injury_status`, a
`birthdate` and a `draft_year`.

Six terms — `inj_status`, `true_age`, `true_experience`, `weekly_sd_rel`, `role_change_snaps`,
`role_change_proj` — plus one board construction, `floor_ceiling_tilt` (floor in the top third of
the board, ceiling in the bottom third, k selected out of sample, floor drawn by **shuffling the
sd assignment** so the marginal distribution is preserved and only the player-to-uncertainty
pairing is destroyed).

All seven are null. The handoff's "most promising thing" — role change — is null in all three
leagues on both constructions, the world's (snap share in week N−1 against the four weeks before
it) and the market's (this week's projection minus last week's).

### `birthdate` uses the Unix epoch as a null sentinel

Found by building `true_age`: the oldest six players on the 2024 wk8 board all came out at exactly
54.8 years. **7,723 of 177,885 weekly weighted rows (4.3%) carry `1970-01-01`**, and 19,786
(11.1%) are blank or NA. 0.0% in 2015–2017, first appearing in 2018 at 2.4%, peaking at **14.4% in
2021**, down to 1.6% in 2025. Jake Browning, Tim Boyle and Kyle Trask are the sentinel, not old
men. The sentinel is now treated as absent and a plausibility band of 18–50 sits on top, with both
counts reported per run.

### A coverage bug that would have discarded the headline metric

The first coverage function read the *first* scope of each season. Week 1 is that scope and
`role_change_snaps` returns nothing before week 3 by construction, so it reported 0.0% for all
seven seasons and the NOT MEASURABLE guard discarded it. Coverage is now the mean over every
scope, with the count of scopes that have any.

---

## The adjudication, honestly accounted

`sim/s7_multiplicity.py`, output `sim/runs/s7-multiplicity.txt`. It introduces no threshold and
fits nothing; it counts tests already run.

```
measurements (term x league) : 72
p-values computed            : 336
hits at p <= 0.05            : 20
expected under a pure null   : 16.4  sd 3.9
excess                       : +3.6  (+0.91 sd)

verdict RESOLVES : 7, across 7 DISTINCT terms
terms resolving in >= 2 leagues : 0
```

The null rate is **exact, not assumed**. A reference-set p over 40 salts can only take k/41;
exactly two of those values are ≤ 0.05, so P(hit) = 2/41 = 0.04878 by construction.

Five of the seven resolutions are in danger_zone and **none** in green_hope. A real property of
football should not be a property of which league you looked at.

### The one lead

`inj_status` at WR is the only (term, place) pair of 336 that hit in two leagues:

```
espn_danger_zone   +0.1125   p 0.0244
espn_green_hope    +0.1919   p 0.0244
sleeper_boyfun     -0.0873   p 0.9512
```

Both hits are the 1-QB ESPN leagues; the reversal is the 10-team SUPERFLEX. It is **off** its
pre-registered locus — `inj_status` was registered board-level — so it is a lead, not a
resolution. The leagues are not independent (same player-weeks, same projections, different
rulebooks), so two-of-three is not converted into a p-value here. What it can do is falsify, and
eighteen other pairs failed that test.

---

## Phase 4 — the board

`sim/s7_phase4.py`, outputs `sim/runs/s7-phase4-<league>.txt`. Run exactly as pre-registered at
`0959e79`, before phases 2 and 3 finished.

```
green_hope    0 survivors. No composite exists.
danger_zone   5 survivors. Weekly out-of-sample +0.0981 (below the 0.10 bar).
              0 of 4 positions improve.
boyfun        2 survivors. Weekly out-of-sample +0.0584. 1 of 4 positions improve.
```

**A board-wide weekly gain that appears at no position is cross-position reallocation, not better
ranking of players against their peers.** The per-position figures are the ones to believe.

### Against the incumbent — three numbers, because two mislead

The incumbent bar is the **ESPN arm**; the board under test is the **FFA arm**. Without the
untreated FFA board in between, the arm difference is attributed to the treatment. The two arms
also do not cover the same seasons — `rank.SEASONS_BY_ARM` excludes espn 2023 — so the incumbent
mean is over six seasons and FFA has seven.

```
                       incumbent   untreated FFA   treated FFA   arm    treatment
espn_green_hope            22.43     (no composite)          —     —            —
espn_danger_zone           28.10             31.32       30.02  -3.22       +1.30
sleeper_boyfun             32.63             31.50       31.03  +1.13       +0.47
```

boyfun's treated board "beats" 32.63 — but the **untreated** FFA board already does. The arm is
worth +1.13 and the treatment +0.47. Swapping projection vendors is not a ranking improvement and
is not what was tested. danger_zone runs the other way: FFA is the worse arm there by 3.22.

Walk-forward (fit 2019–2022, test 2023–2025), seasonal: danger_zone 32.51 → 31.78, boyfun
36.86 → 36.58. green_hope has nothing to walk forward.

**Does the weekly gain transfer to the draft board?** For danger_zone and boyfun the sign is
positive in both modes, but the weekly gains are below the pre-registered material bar and the
terms behind them do not replicate across leagues. The honest answer is that there is no gain
whose reality survives the multiplicity accounting, so the transfer question does not yet have a
subject.

### The split that makes the question meaningful

The model is one function and its inputs are not all available in August.

- **Draft terms** are seasonal priors — last year's snap share, draft capital, a contract. They
  exist before the season and can be confirmed against the incumbent.
- **In-season terms** read a column that only exists once a week has a number — an injury
  designation, a week-over-week role change, this week's dispersion. There is no preseason value,
  so they cannot enter a draft board at all.

Reporting a weekly gain from an in-season term as a draft-board gain is the error phase 4 exists
to avoid. `true_age` was danger_zone's only phase-3 survivor and is excluded from its draft board
for exactly this reason.

---

## Phase 5 — 2026, pre-registered

`sim/s7_phase5.py`, output `sim/runs/s7-2026.txt`, written at `1be0a10` before any 2026 outcome
exists. Five predictions, each falsifiable, each with a direction and a size. P1 re-derives its
numbers from the corpus rather than copying them, and agrees with phase 1 to three decimals across
all 21 season means — two independently written scripts reaching the same number.

Four of the five predict that the null holds. **P3 is the only one whose confirmation would change
the product**: `inj_status` at WR positive in both ESPN leagues, size +0.05 to +0.30, and *not*
positive in the SUPERFLEX. Any of the three parts failing refutes it.

---

## What a later session should not do

- **Do not mine the seven resolutions.** They are seven distinct terms in one league each, against
  16.4 expected false positives. Re-testing them with a different λ grid, a different pool size or
  a different aggregation is how a null becomes a headline.
- **Do not read the per-position figures as scale-specific.** VORP cannot reorder inside a
  position; that is gated.
- **Do not use the shuffle floor as evidence about difficulty.** It is a function of pool size and
  team count.
- **Do not compare a treated FFA board to the ESPN incumbent without the untreated FFA board.**
  The arm is worth more than every treatment measured here.
- **Do not treat two-of-three leagues as replication without saying the leagues share their data.**

## What is worth doing next

- **Check P3 against 2026 when it exists.** That is the one open question this session leaves.
- **The SUPERFLEX VORP result.** Ordering boyfun's board by raw projected points beat ordering it
  by VORP against the VORP outcome. `compute_vorp`'s `rostered_counts` is documented as wrong at
  QB and a SUPERFLEX league is where that would bite hardest. It is a defect in the *incumbent*
  transform, not a new metric, and it is the most promising thing left on the table.
- **Week 18.** Five seasons of outcomes have no projection. If FFA publishes week 18, the corpus
  should be extended rather than the gap papered over.

## Gates and hygiene

```
default run          569 passed, 1 xfailed  (unchanged)
sim gates            661 passed, 0 failed
S7 gates             36, all green
mutation sweep       14 mutations, 11 killed, 3 equivalent, 0 unexpected survivors
live cockpit cache   untouched; see G15 below
CSVs committed       none
```

**G15.** `tests/test_adapters.py` constructs `SleeperAdapter()` with no cache in five places
(lines 34, 59, 70, 183, 207), falling through to the live cockpit cache.
`tests/test_datacache.py:154` shows the one-argument fix, `SleeperAdapter(cache=JsonCache(tmp_path))`.
**This session was not authorised to make it** — the standing rule is never to modify test files
unless explicitly asked, and nothing in this session's instructions lifted it for that file. It
remains open.
