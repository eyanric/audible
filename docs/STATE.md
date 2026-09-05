# audible — carry-forward state

**Read this first. Rewrite it as your final commit.**

This file exists because the previous carry-forward lived outside the repo, so the session that
needed to update it could not reach it. Everything a new session needs to avoid re-deriving
settled facts belongs here, in the repo, versioned with the code it describes.

Rules for editing:

- **Verified facts only.** If it was measured against a live API, say so and give the number.
- **Record the decision, not just the finding.** "Flagged not fixed" is the useful half.
- **Delete what stops being true.** A stale line here is worse than no line.

Last rewritten **2026-09-05**, the morning of both drafts.

---

## The three leagues

`CLAUDE.md` still describes two. There are three, and only two of them draft.

| key | platform / id | shape | market | cockpit |
|---|---|---|---|---|
| `sleeper_boyfun` | Sleeper `1361543954771738624` | 10-team, half-PPR, **SUPERFLEX**, IDP, **19 rounds** | `adp_idp` | **192.168.1.111** |
| `espn_danger_zone` | ESPN `485267278` | 10-team, **full PPR every position**, D/ST, no IDP, 16 rounds | `adp_ppr` | **192.168.1.112** |
| `espn_davis_drive` | ESPN `6012` | 8-team, 1-QB, half-PPR WR/TE, **0.0 RB** | `adp_half_ppr` | none — **drafted 2026-08-30, complete** |

**DDAFFL (`espn_davis_drive`) is finished.** No cockpit serves it. Anything naming `draft_id
6012` or `192.168.1.110` is stale by definition.

**Drafts: `sleeper_boyfun` 19:00, `espn_danger_zone` 20:00, both 2026-09-05.** The Sleeper draft
start time is confirmed from the live draft object: `start_time 1788649234000` = 19:00:34 ET.

---

## League A drifted under us, again. Corrected 2026-09-05 (#51).

`verify-scoring sleeper_boyfun` had not been run against the live league since 2026-08-15. Four
real disagreements, confirmed twice — through the adapter and against a raw `api.sleeper.app`
read:

| | committed | live | now |
|---|---|---|---|
| `DEF` slot | 0 | **1** | corrected |
| `draft_rounds` | 18 | **19** (12 starters + `slots_bn=7`) | corrected |
| `idp_sack` | 6.0 | **3.0** | corrected |
| `idp_int` | 6.0 | **3.0** | corrected |

**It was invisible because the guard cried wolf.** `verify-scoring` reported 78 differing keys,
76 of them the config declining to declare a key the live league declares at `0.0` — the same
rule written two ways, since `score_stat_line` multiplies and sums. The two real drifts were
lines 36 and 38 of that wall. Absent-vs-zero is now excused in both directions and nothing else
is; the command exits 0 on a faithful config for the first time.

**Still drifting, display-only, not corrected:** `median_match = true` in the config against live
`league_average_match: 0`. It touches one CLI print line (`cli.py:50`) and no number. Left for a
decision rather than changed under the wire.

**The verifier still does not check `num_teams`, `draft_rounds` or `slot_eligibility`** —
`SleeperAdapter.verify_structure` compares starting slots and nothing else, which is why the
19-round change came out of the draft object by hand rather than out of the guard. Worth closing.

---

## Both boards vs their own market, measured 2026-09-05

Board rank of the first player at each position against that league's own ADP market. Positive
means **the board wants him earlier than the market takes him** — the direction that costs picks.

### `sleeper_boyfun` — read past these

| position | board rank of first | `adp_idp` rank of first | delta |
|---|---|---|---|
| **DEF** | **74** (LAR) | 287 | **+21.3 rounds** |
| **K** | **83** (Aubrey) | 212 | **+12.9 rounds** |
| **LB** | **28** (Jack Campbell) | 96 | **+6.8 rounds** |
| DB | 105 (Hamilton) | 115 | +1.0 |
| QB | 7 (Josh Allen) | 3 | −0.4 |
| DL | 125 (Burns) | 80 | −4.5 |

**DRAFT-NIGHT RULE, League A only:** the board will offer a **D/ST around its rank 74 and a
kicker around 83**. Both are roughly *twenty and thirteen rounds* before the market takes one.
**Take neither until the last two rounds.** Same for **Jack Campbell at 28** — the board's first
linebacker sits inside the third round while the market's first goes at 96. IDP is real in this
league, but not at that price.

This is the D/ST-and-K inflation League B used to have, and it is **not** fixable by
`replacement_bench_slots`: specialists never enter the bench allocation at all
(`_startable_slots(config, pos) >= 2` gates them out), so the number would move nothing.
`replacement_bench_slots = 0` stays, untouched, for the reason its own config comment gives.

The DEF row was not covered by the pre-registered decision rule, because that rule was written
on the premise that this league had no DEF slot. It does. It is the largest number in the table.

### `espn_danger_zone` — no read-past rule needed

| position | board rank of first | `adp_ppr` rank of first | delta |
|---|---|---|---|
| K | 127 (Aubrey) | 93 | −3.4 rounds |
| DEF | 116 (LAR) | 88 | −2.8 rounds |
| QB | 63 (Josh Allen) | 22 | −4.1 rounds |

Every one is negative: this board fades its specialists relative to the market, which is correct.
That is `replacement_bench_slots = 7` working. **Do not carry League A's read-past rule here.**

**The QB junk-tail pathology has NOT returned.** Pre-registered stop condition was ≥8 QBs inside
the board's top 15. Measured: **1** in League A, **0** in Danger Zone.

---

## The Danger Zone specialist "gaps" cost nothing. Measured, not assumed.

The config records that our vocabulary models neither D/ST yards-allowed (statIds 128–136, live
at +5.0 down to −7.0) nor the kicker 60+ tier (statId 201 is live at **6.0**; the config maps it
to `fgm_50p = 5`). Both are true. **Neither costs the board anything**, because K and D/ST are
never translated: `_pool_entries` assigns them `SOURCE_SPECIALIST`, and `player_projections`
returns `entry.espn_points` — ESPN's own league-applied `appliedTotal` — rather than a computed
score.

Measured over all 90 specialist-sourced players in the pool:

```
max |board points - ESPN appliedTotal| = 0.000000
```

**Expected error: 0.0 pts/season. Rank movement from correcting it: 0.** There is nothing to
correct. `statId 88` (PAT miss) is genuinely absent live, which the config correctly reflects.

What the gap *is* is **latent**. The yards-allowed rule is worth a mean of **−16.3 pts/season**
across the D/ST pool, ranging −37.8 to +5.3 — a 43-point spread that ESPN is currently applying
for us. Anyone who ever "fixes" the vocabulary and starts translating D/ST lines inherits all of
it. Leave it alone.

**`SPECIALIST_GAP`'s own wording is misleading** and invited exactly this investigation: it says
the gap is "worth ~15 pts/season" when the measured board error is `0.000000`. Worth rewording.

---

## Reach annotation: attempted twice, failed twice, not built

`docs/reach-annotation-r2.md` carries the full result; `docs/reach-annotation-gate.md` (branch
`feat/reach-annotation`) carries R1's.

- **R1** fired on `value_rank − current_pick ≥ 40`. Failed specificity: 12 firings against a
  ceiling of 8, six of them quarterbacks.
- **R2** dropped the VORP term for `market_rank − current_pick`, pre-registered before measuring.
  **Failed its sensitivity gate at −3.**

**The headline finding: the DDAFFL draft's "worst pick" was never a reach.** Joe Burrow's
`adp_half_ppr` is **54.5**; he was taken at pick **57**, between Drake Maye (52.3) and Davante
Adams (55.3). He went 2.5 picks *after* the market had him. R1's famous "+52" was
`vorp_rank(109) − pick(57)` — a statement about where this board ranks quarterbacks in a 1-QB
league, not about the pick being early. His consensus rank is **6**.

The replay reproduces R1's recorded numbers exactly (12 firings, 6 QB, Burrow +52), so this is a
measurement of the metric, not of the harness.

R2 also passes G3 at 11.7% — but 13 of its 15 firings are kickers and defences, both below the
ADP noise floor, so the honest unmarked signal over a completed 128-pick draft is **two picks**.

**Do not re-attempt without first answering:** is there any position in either league where the
ADP market both carries signal (RB and WR only, per `#36`'s leave-one-year-out fit) *and* is
disagreed with often enough to be worth a column? On this evidence, no.

---

## `recommend` has no notion of roster balance — still true, still not fixed

**Draft-night rule, until there is a real fix:** `recommend` returns five rows — read all five,
not the first. When you already hold three startable bodies at a position, take the best row
that is not that position. Use `best_available(position="RB")` to see what the run on your thin
position actually costs. The tool ranks value; you own the roster shape.

The dry run produced **10 WR, 2 RB, 1 TE, 1 QB, 1 DEF, 1 K**. Two running backs in a league that
starts two plus a flex is one hamstring from a dead season. Deliberately not patched — the right
fix is marginal value against my own roster, which changes what the board recommends.

## The DDAFFL edge does not transfer

This lived only in `leagues/espn_danger_zone.toml`'s comments, never in this file. It belongs
here.

**Danger Zone is full PPR for every position including RB**, so DDAFFL's fade-the-pass-catching-
back rule is **inverted** there. And its `adp_ppr` matches its scoring exactly rather than
approximately, so it has structurally *less* board-versus-market gap than DDAFFL had — which is
the other half of why the specialist read-past rule above is a League A rule only.

Also from the same file, and worth keeping: in an 8-team league zero kickers and defences go in
the first 128 picks. In Danger Zone the first DEF goes at 88 and the first K at 93, and 10 DEF /
9 K are gone by 160 — roughly one per team, no backups.

---

## Deploy state, 2026-09-05

Both pods on `ghcr.io/eyanric/audible@sha256:91fe2335…`, both Ready, **on different nodes**
(`talos-y0w-bvm` and `talos-lt1-mgf`). Anti-affinity is `preferred`, not `required`, deliberately.
Both report `origin: disk`, `from_disk 6 / from_network 0`.

**Read `origin` from `/healthz`, and the league key from `/api/state`. Neither endpoint has
both.** `/api/state`'s `data` block is `{sources, oldest_age_s, oldest_days, stale}` and carries
**no** `origin` field at all; `/healthz` carries `origin` but has never carried a league key.
Any check that greps one endpoint for the other's field returns empty on a perfectly healthy
cockpit.

The origin dance itself (from haven #363, measured on the live pod): a fresh pod reports `mixed`;
`refresh-data` changes **nothing**, because `origin` is `_ORIGINS`, a process-global in
`adapters/nflverse.py` written once per source at load, and `refresh-data` runs in a separate
process; a **container** restart re-reads the surviving `emptyDir` and converges to `disk`; a
**pod roll** wipes the `emptyDir` and goes back to `mixed`. **Refresh after the last deploy,
never before.**

### haven needs attention and it is not ours to do

- **The Renovate freeze on `ghcr.io/eyanric/**` is NOT merged — the opposite is.** PR #338 added
  a freeze; **PR #344 deleted it on 2026-09-02**. The live `renovate.json5` rule for that prefix
  is `automerge: true, minimumReleaseAge: '0 days'`. A digest bump merges itself unattended.
- **haven PR #352** — "[DO NOT MERGE UNTIL FRIDAY] flux: freeze app reconciliation for the
  2026-09-05 draft weekend" — is still open. Today is that Friday.
- **The public MCP endpoint is broken.** `mcp-audible` proxies to
  `http://audible.audible.svc.cluster.local:80`, and **no Service named `audible` exists** in
  that namespace — only `audible-boyfun` and `audible-danger-zone`. The proxy is Ready because
  its probes are TCP against its own port. This is why the `audible-mcp` connector 502s.

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
- **Consensus is the projection of record.** The opportunity model lost out-of-sample at every
  position; it rides as a flag overlay, never as a multiplier.
- **`value_metric = "vorp"` for League B**, not scarcity/VONA — VONA edged it in backtest
  (+28 vs +24) but the current implementation has a junk-tail pathology on flat positions that
  produces a QB-dominated board. Tracked; ship on VORP.
- No model calls inside `audible`, ever. No writes to any platform.

---
## Data enrichment (2026-08-26) — what shipped, what was measured and refused

### Lane 1 shipped: usage context, display-only

Six numbers per player: target share, air-yards share, route participation, snap share and
depth-chart slot (2025 observed), plus the 2026 bye. All six are in `_slim()`, so the MCP
surface carries them.

**They are NOT board columns.** The `Tgt%` / `Rte%` pair this section originally described
was dropped when #35 was retargeted onto main: main had already spent that column budget on
`Bye` and `vs ESPN`, and relaying out a thumb-drivable table on the morning of a live draft
was not a trade worth making. The numbers reach the phone through MCP, which is the surface
actually queried while the clock runs.

**Nothing enters the sort, and it is asserted, not promised.** `draft/usage.py` is imported
by the state builder and the MCP surface only — never `board.py`, `value/`, `scoring/`. The
lookup happens after the board is built and ranked. `usage did not enter the sort` walks the
board in rank order asserting VORP never rises; the `usage_in_sort` mutation reorders the
board by target share while keeping ranks a clean 1..N and only that check catches it.

**Route participation is a PROXY.** nflverse carries no charted routes-run per player.
`load_participation` does carry, per play, the eleven men on the field and the route charted
on that play, so the number is *share of the team's charted-route plays he was on the field
for*. A tight end who stays in to block counts. Validated 2025 before building: Jefferson
95.6%, Chase 91.5%, St Brown 91.5%, McBride 94.0%, Henry 39.5%.

**CLAUDE.md's "route participation is a known gap" is now stale for 2025.** It was true
in-season; the delay has passed and `load_participation([2025])` returns 45,184 rows over
285 games.

### The inventory that motivated it

The opportunity model consumed **11 of ff_opportunity's 159 columns**, **5 of player_stats'
150**, and **2 of rosters' 36**. `target_share` and `air_yards_share` were already sitting
in the cached weekly stats, unread. `load_snap_counts` and `load_nextgen_stats` had cached
adapter wrappers and zero call sites.

### Cache: derived-and-pinned, not raw

| pinned | rows | size |
|---|---|---|
| `route_participation_2025` (derived) | 978 | 14 KB |
| `depth_chart_slots_2026` (derived) | 3,182 | 20 KB |
| `snap_counts_2025` | 26,612 | 244 KB |
| `schedules_2026` | 272 | 23 KB |

Raw participation is 45k rows carrying an eleven-id string per play; raw depth charts are
472k rows. Pinning either whole would bloat the cache the launcher reads before kickoff, so
the aggregation is cached instead of its input. Fresh process: `from_disk=6, from_network=0`
→ `/healthz` origin `"disk"`, launcher still says **Data: from DISK**.

**LA vs LAR.** nflverse schedules spell the Rams `LA`; the board says `LAR`. One team, a
silently blank bye, no other symptom. A first fix also mapped the plausible-looking
historical aliases and broke Washington, where both sides already said `WAS`. Only the
measured difference is mapped. `every board team resolves to a bye week` asserts the join.

### Lane 2 REFUSED — measured, not material

`survival_pct` is None wherever `adp_known` is false and `grab_now` leads `recommend`'s
sort, so unpriced players are invisible to scarcity. The mechanism is real. The magnitude is
not:

| window | unpriced |
|---|---|
| whole board (3,302) | 2,229 (67.5%) |
| **top 128 — the entire draftable window** | **0** |
| top 300 | 1 |
| top 500 | 40 (8.0%) |

Every player reachable in 8×16 picks already has ESPN ADP; the first unpriced sits at rank
262. Filling from Sleeper ADP would add a low-confidence, mock-contaminated source that
touches survival in order to fix zero draftable players. **Not built.** Re-measure if the
league deepens or the board is ever served past ~rank 250.

### Bye-week feasibility of the slot-8 dry run — the answer is NO

Its two RBs are Derrick Henry (BAL, bye 13) and James Cook (BUF, bye 7). A legal lineup does
**not** exist in every week:

| wk | on bye | unfillable |
|---|---|---|
| 7 | Cook | **RB** |
| 8 | Purdy, HOU | **QB, DEF** |
| 13 | Henry | **RB** |
| 14 | McBride, Aubrey | **TE, K** |

Structural, not unlucky: `RB` slots take only `RB` and the roster holds exactly two, so any
RB bye breaks it. Same single-depth flaw at QB, TE, DEF, K — `recommend` drafted ten WRs and
exactly one of everything else, which is its slack arithmetic working as written (need binds
only when slack hits zero). **Flagged, not fixed:** fixing it changes what the board
recommends, which is out of bounds until the C-B backtest exists.

### Candidates logged, deliberately not built

- **Vegas team totals** — per instruction: candidate only.
- **Sleeper ADP fallback** — see Lane 2 above; revisit only if the unpriced count inside the
  draftable window stops being zero.
- **NGS receiving** (`avg_separation`, `avg_cushion`, `percent_share_of_intended_air_yards`)
  and **PFR advanced rec** (`adot`, `drop_percent`, `ybc_r`) are available and unused.
- Nothing above enters the sort before the C-B backtest.

---

---

## Open / next

**Ordered by what breaks the draft, not by what is interesting.**

1. **haven: merge #352 and restore a Renovate freeze** before pinning any new digest. Without
   the freeze a digest PR self-merges and rolls both pods at ~01:00 ET Sunday.
2. **haven: point `mcp-audible` at a Service that exists**, or add one. The public MCP surface
   is down.
3. **`recommend` has no notion of roster balance** - above. Read all five rows.
4. **`verify_structure` checks only starting slots.** Add `num_teams` and `draft_rounds`; League
   A's 19-round change had to be found by hand.
5. **`median_match` vs live `league_average_match: 0`** - decide and either correct or delete
   the field.
6. **`SPECIALIST_GAP` says "~15 pts/season" where the measured error is 0.000000.** Reword.
7. **Reach annotation: do not re-attempt** without answering the question at the end of that
   section. Two pre-registered gates have now failed on it.
