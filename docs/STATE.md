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

## Where the project is

| | |
|---|---|
| Phase | 2a complete (ESPN adapter). **2b complete (ESPN sync)** — the cockpit runs against League B. |
| Leagues | A = Sleeper `sleeper_boyfun` (10-team, superflex, IDP). B = ESPN `espn_davis_drive` (8-team, 1-QB, no IDP). |
| Board source | Sleeper stat lines for **both** leagues, scored through each league's own weights. League B's `draft` output carries a header saying so. |
| Live sync | Both platforms, one poll loop, behind `draft/sync.py`. `serve --league espn_davis_drive` verified: `ok:true`, 3,300 players, 0 picks pre-draft, seat 8 derived. |
| Not started | Phase 3, Phase 4. |

**`live` is Sleeper-only** and says so — it polls the adapter directly rather than going
through the cockpit. League B's live surface is `serve`.

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

This stops `build_board` dead for **both** leagues, because the crosswalk is the first thing
it builds. `adapters/nflverse.py` now tries nflreadpy first and falls back to the raw host for
the two affected loaders (`load_id_map`, `load_rankings`). Primary-first means it resumes using
upstream on its own once fixed; **delete the workaround block then.**

The fallback reads every column as a string on purpose — this is an ID spine, and a
`sleeper_id` inferred as a float becomes `"4034.0"` the moment anything stringifies it, failing
the join silently for every player instead of loudly for none.

**nflreadpy caches in memory only** (`CacheMode.MEMORY`), so every process start re-downloads.
Repeated board builds in one session will earn a `429` from GitHub raw; it clears in minutes.

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

## Open / next

- **Next session, promoted above the rest of Phase 3:** measure how ESPN-anchored each opponent
  is, by correlating each manager's pick sequence against ESPN's per-season draft ranks for
  2023–2025.

  This decides whether any scoring edge is actionable. The points delta does **not** translate
  into a ranking mispricing at the top, because ESPN's STANDARD ordering already tracks PPR
  there. The surviving edge is the **Henry archetype** — pure rushing backs, undervalued by
  anyone using generic half-PPR rankings, correctly valued by ESPN's board and by ours. Which
  opponents sit in which camp determines whether that is exploitable.

- **The `image` workflow is red and undiagnosed** (as of PR #10). It fails at "Set up job",
  step 1, before any step runs — twice, in 56s and 70s. `.github/workflows/image.yml` is
  byte-identical to the version that passed on PR #9 two hours earlier; the referenced docker
  actions still resolve; the `ci` job passes on the same runner label. The job log was not
  readable without GitHub auth (`gh` unauthenticated, no Actions-logs tool on the MCP server).
  **Get the "Set up job" error before trusting the Docker image path.** Delete this entry once
  it is understood.

- **Needs Eric:** the `image` failure above; draft date when set; the manual-pick re-run is
  still outstanding. Only the first blocks anything, and only the Docker path.
