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

## DRAFT: Friday 28 August, 8:30. ESPN league 6012.

Everything below serves that date. **Code freeze Thursday 27 August** — no merges, no
rebuilds, no config edits after it.

Two tracks. **Track A never slips for Track B.**

| by | track A | track B |
|---|---|---|
| Mon 17 | build failure diagnosed — **done** | — |
| Tue 18 | data on disk, offline board proven — **done** | **B1 anchoring — done** |
| Wed 20 | latency outcome — **blocked, see below** | B2 evaluation harness + 384-pick run |
| Fri 22 | Sleeper mock rehearsal — **needs Eric** | B3 corpus harvest + provenance |
| Sun 24 | ESPN runbook — not started | B3 analysis + B4 wins conversion |
| Tue 26 | digest pinned, offline re-proven | B5, B6 |
| Wed 27 | **freeze**, paper board | B7 if it stands up |

**A1 latency is blocked and it is not a scheduling problem.** Temp league `102010124` read
read-only this session: `drafted: false`, `inProgress: false`, **0 real picks** — the draft has
not been run. `scripts/espn_latency.py` exists and `data/cache/latency.jsonl` is empty, so
nothing has been measured. Latency cannot be reconstructed after the fact; it needs the script
running *while* picks happen. Until then the sync-vs-manual mode decision is unmade, and
manual entry is the safe assumption.

## Where the project is

| | |
|---|---|
| Phase | 2b complete. ESPN adapter, ESPN sync, and an offline-capable board. |
| Leagues | A = Sleeper `sleeper_boyfun` (10-team, superflex, IDP). B = ESPN `espn_davis_drive` (8-team, 1-QB, no IDP). |
| Board source | Sleeper stat lines for **both** leagues, scored through each league's own weights. League B's `draft` output carries a header saying so. |
| Live sync | Both platforms, one poll loop, behind `draft/sync.py`. Verified: `ok:true`, 3,300 players, 0 picks pre-draft, seat 8 derived. |
| Data | **On disk.** Board builds with the network unplugged — see below. |
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

## B1 — opponent anchoring: settled, and the answer is "no edge here"

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

**What this means for the 28th:** the RB-reception split is *not* an exploitable ranking edge
against this room. Every opponent's behaviour is consistent with reading ESPN's own board,
which already prices non-receiving backs correctly. Do not plan to steal Henry-types late —
this room is not undervaluing them. The scoring findings still hold (they rest on arithmetic,
not on this), but they do not convert into a draft-day exploit here.

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

- **Manual entry is built but unmeasured.** `/` → type → **Enter** marks the top filtered
  match; the target is named on screen first; the query clears and focus stays put; Ctrl+Z
  undoes without leaving the box. Verified live that marking advances the clock and undo is a
  true inverse. **The three-second standard has not been measured** — that needs a human at a
  keyboard, and it belongs to the rehearsal. On branch `feat/manual-entry`, not yet merged.

- **Blocking, needs Eric:**
  1. **Run the temp draft in league `102010124` with `scripts/espn_latency.py` already
     running.** The league exists and is configured; nobody has drafted in it, so there is
     nothing to measure. Latency cannot be reconstructed afterwards — the script has to be
     watching while picks happen. Two or three rounds is enough. Under ~15s → sync leads;
     over ~30s or batchy → manual entry leads. Until then, assume manual entry.
  2. **The manual-pick re-run and a Sleeper mock**, three rounds, cockpit open. Free, and it
     exercises sync, staleness, grab-now, snake math and the UI — all shared with ESPN. The
     tool has never been used in a live draft by a human.

- **Still to do before the freeze:** ESPN runbook (it still assumes Sleeper) with the fallback
  ladder sync → manual → `audible live` → paper; digest pinned Wed 26; paper board printed
  Thu 27.

- **Track B, next:** B2 (384-pick evaluation, leak-free), then B3 (corpus widening — this is
  what makes the interval tight enough to act on; 384 observations detect a large edge and
  nothing subtle), B4 (Eric's picks + wins conversion), B5 (tendencies), B6 (silent-empty
  guard — B1 just produced a fifth occurrence, the rank tail), B7 (Phase 4 metrics, only
  after B2/B3 report).

  **B1 is done and its answer constrains the rest:** there is no ranking edge against this
  room from the scoring split, so B2/B3 are measuring whether the board is better *in
  general*, not whether it exploits these seven managers.
