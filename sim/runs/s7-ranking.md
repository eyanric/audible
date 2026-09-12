# S7 — one ranking system, validated weekly

Written so a later session needs neither the PR nor the handoff. Every number here has a
committed script and a committed output behind it; the script is named beside each.

**This document has been rewritten twice, both times because the adversarial review overturned
the headline.** The corrections are kept in the text rather than erased, because the mistakes are
the most transferable part of the session.

---

## The result, in one paragraph

Twenty-four terms were tested in three leagues — seventeen signals the handoff listed as prior
nulls, plus seven new metrics and board constructions built for this session — over 118 weekly
scopes and seven seasons. That produced 336 hypothesis tests and **19 hits at p ≤ 0.05 against
13.1 expected under a pure null** (+1.31 sd, after correcting both the per-test null rate and the
dependence between tests). **Not one (term, place) pair hit in two leagues. Three pairs hit in
opposite directions in different leagues** — the same term helping in one and measurably harming
in another. The weekly sample did not resolve what six seasonal observations could not, and the
incumbent draft board stands.

The most useful output of the session is not a ranking. It is four data defects, two
methodological retractions, and a harness that now fails on purpose when broken.

---

## What was measured, and on what

- **Projections**: `sim/data/ffa_corpus/`, the FFAnalytics weekly `raw` exports landed by
  `audible#90` and `audible#91`. 612 files, gitignored. `raw`, never `proj` — a `proj` export is
  scored under the FFAnalytics default league and capped at 36 QB per season, which cannot serve a
  10-team SUPERFLEX.
- **Outcomes**: `player_stats_{2019..2025}.parquet`, scored under each league's own rulebook.
- **Metric**: round-weighted rank error, symmetric indexing, settled in `audible#85`/`#88`.
- **Scale**: VORP on both sides, which is what the draft board ships. Raw points reported beside it.

**The window is 118 scopes, not the 169 the corpus offers.** The outcome side binds:
`player_stats` is pinned for 2019–2025 only, so 51 weekly projection files sit on disk with no
pinned outcome and are not scored. Nothing is substituted. Scored player-weeks are 15,104 /
18,880 / 22,420 for green_hope / danger_zone / boyfun; the *candidate* pool is 36,201, and an
earlier version of this report published the candidate count as though it were the sample.

---

## Phase 1 — the harness, and two retractions

`sim/s7_weekly.py`, `sim/s7_phase1.py`, output `sim/runs/s7-phase1.txt`, gates
`sim/test_g_s7.py` (36).

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
problem were harder.

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
   Gated, so no later phase can read them as scale-specific.

### Coverage gap, previously undocumented

The regular season has been **18 weeks since 2021** and the corpus stops at week 17. For 2021–2025
one week of realised production per season has no projection and can never be scored, and a
seasonal per-game outcome includes production a weekly aggregate built from this corpus cannot.

---

## Phase 2 — seventeen prior nulls, re-adjudicated weekly

`sim/s7_phase2.py`, outputs `sim/runs/s7-phase2-<league>.{txt,jsonl}`.

Seventeen terms, not sixteen: the handoff lists `age / experience` as one line and it is two
terms. Nothing was dropped and nothing added.

### RETRACTED, twice: the design, then the floor

**First the strength.** The original design fixed λ at 0.10 and adjudicated on "beats the floor".
At a fixed strength **every** term measures negative — a random term at λ 0.10 costs about −0.55
RWRE, because multiplying a good ranking by (1 + 0.1·z) with noise for z can only add noise. So
"beats the floor" would have resolved terms that leave the board *worse than not touching it*.
`snap_share` read −0.3051 board-wide with p 0.024 and was one commit from publication. Strength is
now selected **leave-one-season-out** over a grid containing 0.0, and the floor goes through the
identical selection, so the p tests against *selection noise* rather than against zero. In 31 of
72 measurements the selection chose λ = 0 in every fold.

**Then the floor itself, which the review refuted.** A reference-set p is only meaningful if the
salt and the signal are exchangeable under the null. The salt was a `Uniform(-1, 1)` hash.
`inj_status` is 95% exactly zero and demotes a handful of players hard; the hash jiggles everyone
gently. Those are not the same kind of intervention. Measured by the reviewer: `inj_status` at WR
read **p 0.0244 against the hash and 0.0976 / 0.3415 against a permutation of its own values**,
because merely shuffling *which* player is listed Out already buys +0.119 and +0.081 RWRE — 62%
and 72% of the observed effect. That pair was the session's only cross-league replication and the
entire subject of its 2026 pre-registration.

The same defect broke the null rate in the other direction. `p = (1 + #{f ≥ obs})/41` cannot reach
0.05 when three or more of the 41 values tie at the maximum, and out-of-sample selection parks
most floor draws on exactly 0.000. For five of six sampled terms the null probability of a hit was
**zero**, not 2/41.

The floor is now a **permutation of the term's own values** among the players it covers: marginal
distribution preserved exactly, value-to-player pairing destroyed, exchangeable by construction. A
term that is constant within every position is permuted *across* positions instead, because
dealing four position-level rates to individual players would manufacture spread the term provably
cannot have. `s7_phase3.run_tilt` already used this null for its sd shuffle, so the session had
been inconsistent with itself.

### Three verdict bugs, same review

- `material` was `max(abs(...))`, so the **magnitude of a term's own damage** could certify it.
  `ngs_separation` in danger_zone scored −0.1404 board-wide at p 0.9268 — it lost to 38 of 40
  floor draws — shipped as `RESOLVES`, and entered the composite. Materiality is now read at the
  place that actually qualified, with its sign; that record is now `resolves but immaterial` with
  a board-level harm.
- `material` ignored a hit off the pre-registered locus, so `inj_status` at WR read immaterial at
  +0.1919. An off-locus hit is still never a resolution — moving a locus afterwards is how a null
  becomes a headline — but it now carries its own materiality.
- The `HARM` branch tested `p ≤ 0.05` with a negative effect, which is backwards: `reference_p` is
  one-sided for improvement, so a harm reads p near 1.0. It fired **zero** times in 72
  measurements while five terms sat past the material harm bar. It now reads off `harm_p` and
  fires six times.

### Two of the seventeen had never been tested at all

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
session's finding rather than citing it. Positions where a term holds one distinct value are
reported as *structurally zero* and no p is printed for them.

---

## Phase 3 — new metrics

`sim/s7_metrics.py`, `sim/s7_phase3.py`, outputs `sim/runs/s7-phase3-<league>.{txt,jsonl}`.

The board reads one input and discards the rest of the file it was built from. Every weekly FFA
export carries, per player and unused: a standard deviation for every stat, an `injury_status`, a
`birthdate` and a `draft_year`.

Six terms — `inj_status`, `true_age`, `true_experience`, `weekly_sd_rel`, `role_change_snaps`,
`role_change_proj` — plus one board construction, `floor_ceiling_tilt` (floor in the top third of
the board, ceiling in the bottom third, k selected out of sample, floor drawn by shuffling the sd
assignment).

**Twenty-one measurements: 17 null, 2 resolve-but-immaterial, 1 RESOLVES, 1 HARM.** The one
resolution is `true_age` in danger_zone (+0.1791, p 0.0244) and it appears in neither other
league. `role_change_snaps` in boyfun is a material harm. `floor_ceiling_tilt` is null in all
three. The handoff's "most promising thing" — role change — is null or harmful everywhere, on both
constructions: the world's (snap share in week N−1 against the four weeks before it) and the
market's (this week's projection minus last week's).

### `birthdate` uses the Unix epoch as a null sentinel

Found by building `true_age`: the oldest six players on the 2024 wk8 board all came out at exactly
54.8 years. **7,723 of 177,885 weekly weighted rows (4.3%) carry `1970-01-01`**, and 19,786
(11.1%) are blank or NA. 0.0% in 2015–2017, first appearing in 2018 at 2.4%, peaking at **14.4% in
2021**, down to 1.6% in 2025. Jake Browning, Tim Boyle and Kyle Trask are the sentinel, not old
men. The sentinel is treated as absent and a plausibility band of 18–50 sits on top, with both
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
   of which CANNOT return a hit at 0.05, because of ties in their own floor: 56
hits at p <= 0.05            : 19
expected under a pure null   : 13.1   (a flat 2/41 would have said 16.4)
sd, independent              : 3.5
sd, corrected (phi 1.63)     : 4.5
excess                       : +5.9  (+1.31 sd)

(term, place) pairs hit in >= 2 leagues : 0
(term, place) pairs hit in exactly 1 league : 19
```

Two corrections from the review are in those numbers. **The null rate is per test**, enumerated
from each test's own tie structure rather than assumed flat — 56 of the 336 tests could not have
returned a hit at all, and counting them as though they could inflated the benchmark from 13.1 to
16.4. **The variance is not binomial**: the board p and four positional p values inside a record
share the same 40 floor draws, and the measured overdispersion is φ = 1.63.

### Three sign conflicts, and zero replications

```
availability at board:   danger_zone HELPS +0.1655   green_hope HARMS -0.1602
snap_share  at WR:       green_hope  HELPS +0.1178   boyfun     HARMS -0.1104
snap_share  at TE:       danger_zone HELPS +0.0409   boyfun     HARMS -0.0368
```

The three leagues share their weeks, their players and their projections and differ only in a
rulebook. `availability` helping by +0.166 in one and harming by −0.160 in another, both
significant, is not a property of football. **More (term, place) pairs contradict across leagues
than replicate: three against zero.**

Seven verdicts of `RESOLVES` across six distinct terms. One term — `snap_share` — resolves in two
leagues, but at **two different places** (TE in danger_zone, WR in green_hope), and at WR it is a
significant *harm* in the third. In green_hope its board-level strength selection chose λ = 0.0 in
every fold, so the term as applied to the board does nothing at all; phase 4 excludes it for that
reason.

---

## Phase 4 — the board

`sim/s7_phase4.py`, outputs `sim/runs/s7-phase4-<league>.txt`. Run as pre-registered at `0959e79`,
before phases 2 and 3 finished.

```
green_hope    0 survivors. No composite exists.
danger_zone   4 survivors (3 draft-capable). Weekly out-of-sample +0.1800.
              0 of 4 positions improve. Seasonal out-of-sample 32.51 -> 30.26.
boyfun        2 survivors. Weekly out-of-sample +0.0584 (below the 0.10 bar).
              1 of 4 positions improve. Seasonal out-of-sample 36.86 -> 36.58.
```

**A board-wide gain that appears at no position is cross-position reallocation, not better
ranking of players against their peers.** danger_zone improves the board by +0.18 out of sample
while making all four positions worse. The per-position figures are the ones to believe.

### Leave one out: which term is carrying it

```
danger_zone, seasonal out-of-sample, all 3 draft terms : +2.2425
  without snap_share    +2.0214   (worth +0.2210)
  without target_share  +0.5003   (worth +1.7422)
  without availability  +0.5675   (worth +1.6749)

boyfun, seasonal out-of-sample, all 2 draft terms      : +0.2783
  without depth_slot          +0.2289   (worth +0.0494)
  without ngs_time_to_throw   +0.5053   (worth -0.2269)
```

danger_zone's +2.24 rests almost entirely on `target_share` and `availability` — and
`availability` is the term that helps by +0.166 in danger_zone and harms by −0.160 in green_hope.
In boyfun, `ngs_time_to_throw` is a surviving term whose removal **improves** the composite by
0.23: it was resolved on a board-wide p and it damages the composite it qualified for.

### Against the incumbent — three numbers, because two mislead

The incumbent bar is the **ESPN arm**; the board under test is the **FFA arm**. Without the
untreated FFA board in between, the arm difference is attributed to the treatment. The two arms
also do not cover the same seasons — `rank.SEASONS_BY_ARM` excludes espn 2023 — so the incumbent
mean is over six seasons and FFA has seven.

```
                       incumbent   untreated FFA   treated FFA   arm    treatment
espn_green_hope            22.43     (no composite)          —     —            —
espn_danger_zone           28.10             31.32       29.99  -3.22       +1.33
sleeper_boyfun             32.63             31.50       31.03  +1.13       +0.47
```

**That "treatment" column is contaminated and the committed output says so.** The gain is selected
on the fit seasons 2019–2022 and evaluated over the incumbent's six seasons, four of which *are*
the fit seasons. The clean numbers are the out-of-sample ones above: danger_zone 32.51 → 30.26,
boyfun 36.86 → 36.58.

boyfun's treated board reads 31.03 against the incumbent's 32.63 — but the **untreated** FFA board
already reads 31.50. The arm is worth +1.13 and the treatment +0.47. Swapping projection vendors
is not a ranking improvement. danger_zone runs the other way: FFA is the worse arm there by 3.22,
and even treated it does not reach 28.10.

### Does the weekly gain transfer to the draft board?

Both surviving composites show a positive sign in both modes, and both seasonal out-of-sample
gains clear the 0.10 material bar (+2.24 and +0.28). **The sign transfers. The evidence does not.**
No (term, place) pair replicates across leagues, three contradict, the hit count is within 1.31 sd
of a pure null, and danger_zone's gain evaporates when either of two terms is removed — one of
which reverses sign in another league. There is no gain whose reality survives the accounting, so
the transfer question does not yet have a subject.

### The split that makes the question meaningful

The model is one function and its inputs are not all available in August.

- **Draft terms** are seasonal priors — last year's snap share, draft capital, a contract.
- **In-season terms** read a column that only exists once a week has a number: an injury
  designation, a week-over-week role change, this week's dispersion. There is no preseason value,
  so they cannot enter a draft board at all.

`true_age` was danger_zone's only phase-3 survivor and is excluded from its draft board for
exactly this reason.

---

## Phase 5 — 2026, pre-registered

`sim/s7_phase5.py`, output `sim/runs/s7-2026.txt`. Five predictions, each falsifiable, each with a
direction and a size. P1 re-derives its numbers from the corpus rather than copying them, and
agrees with phase 1 to three decimals across all 21 season means.

Two corrections from the review are in it. **P1 now uses a prediction interval**,
`t(6,.975)·s·√(1+1/7)`, not `2·sd` — which covers a new season only about 89% of the time.
**P1 also could not discriminate its own hypothesis**: all three leagues decline across the window
and the OLS extrapolation for 2026 sits inside the flat interval, so both models predicted a pass.
The trend is now stated beside the flat number with a line that separates them. **P2 is labelled
weak** — it confirms about 87% of the time under a pure null — and kept, because deleting a weak
prediction after writing it is worse than saying it is weak.

**P3 has no subject.** Under the corrected floor, nothing hit at p ≤ 0.05 in more than one league,
so the prediction is that a 2026 re-run produces no cross-league pair either. It reads that from
the committed records rather than hardcoding a lead, because a hardcoded lead becomes a wrong fact
the moment the adjudication is corrected — which happened twice here.

---

## What a later session should not do

- **Do not mine the seven resolutions.** Six distinct terms, one league each, against 13.1
  expected false positives — and three of them contradict a different league at the same place.
- **Do not read `availability` as a signal.** It is four position-level numbers and it reverses
  sign between two leagues that differ only in team count and scoring.
- **Do not use a hash as a reference set for a term whose values are not uniform.** That is what
  cost this session two headlines. Permute the term's own values.
- **Do not assume a reference-set p can reach 0.05.** Count the ties first.
- **Do not read the per-position figures as scale-specific.** VORP cannot reorder inside a
  position; that is gated.
- **Do not use the shuffle floor as evidence about difficulty.** It is a function of pool size and
  team count.
- **Do not compare a treated FFA board to the ESPN incumbent without the untreated FFA board.**
  The arm is worth more than every treatment measured here.
- **Do not read the incumbent comparison table's "treatment" column as out-of-sample.** It is not.

## What is worth doing next

- **The SUPERFLEX VORP result.** Ordering boyfun's board by raw projected points beat ordering it
  by VORP against the VORP outcome. `compute_vorp`'s `rostered_counts` is documented as wrong at
  QB and a SUPERFLEX league is where that would bite hardest. It is a defect in the *incumbent*
  transform, not a new metric, and it is the most promising thing left on the table.
- **Check the 2026 predictions when 2026 exists.** That is the only clean holdout left.
- **Week 18.** Five seasons of outcomes have no projection. If FFA publishes week 18, extend the
  corpus rather than paper over the gap.
- **A bigger reference set.** 40 permutations floors p at 0.0244 and ties push it higher. The
  handoff notes 79 draws buys 2.5%; the tie structure means the realised resolution is often
  worse than the nominal one, and `achievable_p` now reports it per test.

## Gates and hygiene

```
default run          569 passed, 1 xfailed  (unchanged)
sim gates            687 passed, 0 failed, 0 skipped
S7 harness gates     36, all green   (sim/test_g_s7.py)
S7 adjudication      22, all green   (sim/test_g_s7_adjudication.py)
mutation sweep       27 mutations, 23 killed, 4 equivalent, 0 unexpected survivors
                     across s7_weekly, s7_phase2 and s7_phase4
live cockpit cache   untouched; see G15 below
CSVs committed       none
```

The adjudication gates exist because the review found that **nothing tested the half of this
session that produced the result**: all 36 harness gates import `rank`, `room` and `s7_weekly`, so
`loso`, `reference_p`, the floor and the verdict logic had no coverage at all, and the mutation
sweep inherited the same blind spot. The three verdict bugs above would each have been caught by
one gate.

**G15.** `tests/test_adapters.py` constructs `SleeperAdapter()` with no cache in five places
(lines 34, 59, 70, 183, 207), falling through to the live cockpit cache.
`tests/test_datacache.py:154` shows the one-argument fix,
`SleeperAdapter(cache=JsonCache(tmp_path))`. **This session was not authorised to make it** — the
standing rule is never to modify test files unless explicitly asked, and nothing in this session's
instructions lifted it for that file. It remains open.
