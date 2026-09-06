# audible — carry-forward state

**Read this first. Rewrite it as your final commit.**

This file exists because the previous carry-forward lived outside the repo, so the session that
needed to update it could not reach it. Everything a new session needs to avoid re-deriving
settled facts belongs here, in the repo, versioned with the code it describes.

Rules for editing:

- **Verified facts only.** If it was measured against a live API, say so and give the number.
- **Record the decision, not just the finding.** "Flagged not fixed" is the useful half.
- **Delete what stops being true.** A stale line here is worse than no line.

Last rewritten **2026-09-05, 22:30 ET**, after all three configured leagues had drafted.

---

## THE ONLY DRAFT LEFT IS ONE WE CANNOT READ

**ESPN league `73131979`. Tuesday 2026-09-08, 19:00 ET. Snake, 8 teams, Eric says seat 1.
There is no config for it and no cockpit that can serve it.**

It lives on a **SECOND ESPN account**. Measured 2026-09-05 with the account-1 cookies in `.env`:

| league | HTTP | note |
|---|---|---|
| `6012` | **200** | `Davis Drive Alumni FF League`, size 8 |
| `485267278` | **200** | `2026 Danger Zone`, size 10 |
| **`73131979`** | **401** | `You are not authorized to view this League.` |
| `999999999999` (control) | 400 | `Invalid parameter for 'leagueId'` |

The control matters: a bad id returns **400**, so the 401 means the league **exists and is
private**, not that the id is wrong. An anonymous request returns the same 401. `adapters/espn.py`
reads `ESPN_SWID` / `ESPN_S2` from the process environment via `_cookie(...)` — **one process,
one account** — so nothing can be done against this league until `.env` (or the environment)
carries account 2.

**This is the whole blocker.** Everything on the "Open / next" list that touches 73131979 is
waiting on it and on nothing else.

---

## The leagues

| key | platform / id | shape | market | cockpit | draft |
|---|---|---|---|---|---|
| `sleeper_boyfun` | Sleeper `1361543954771738624` | 10-team, half-PPR, SUPERFLEX, IDP | `adp_idp` | 192.168.1.111 | **complete** |
| `espn_danger_zone` | ESPN `485267278` | 10-team, full PPR every position, 16 rounds | `adp_ppr` | 192.168.1.112 | **complete** (160 picks) |
| `espn_davis_drive` | ESPN `6012` | 8-team, 1-QB, half-PPR WR/TE, 0.0 RB | `adp_half_ppr` | none | **complete** (128 picks) |
| **(none yet)** | **ESPN `73131979`** | **8-team snake, seat 1 (unverified)** | ? | **none** | **2026-09-08 19:00** |

All three configured leagues report `drafted: true` / status `complete` as of 2026-09-05 22:29
ET. Their draft-night rules below are **historical**; keep them for method, not for tonight.

---

## What shipped 2026-09-05: structure verification asks about teams and rounds

`verify_structure` compared starting lineup slots **and nothing else** on both adapters. It now
reports `num_teams` and `draft_rounds` as the same `(name, config, live)` rows, same non-zero
exit. `_print_structure` says STRUCTURE DRIFT rather than ROSTER DRIFT, and `cmd_live`'s bespoke
team-count check is gone — one place to be wrong.

**ESPN derives rounds two ways and requires agreement**: `max(roundId)` over the pre-draft pick
slate, and `sum(lineupSlotCounts) − IR`. Disagreement raises `EspnDataError` (exit 2) instead of
breaking the tie. An **absent** slate is not a disagreement — `draft_rounds_from_slate` returns
None and verification proceeds — so a league whose grid ESPN has not built yet still verifies.

Measured live, both ways, both reachable leagues:

| league | slots − IR | max(roundId) | slate rows | teams × rounds | config |
|---|---|---|---|---|---|
| `485267278` | 16 | 16 | 160 | 160 ✓ | 16 |
| `6012` | 16 | 16 | 128 | 128 ✓ | 16 |

**Sleeper rounds do NOT come from `settings.draft_rounds`.** Measured against live League A: that
field serves **3** on a twenty-slot roster — the keeper artifact this league's own config notes
call vestigial. Rounds are the roster spots that get drafted (starters + bench, `IR`/`TAXI`
excluded) = **20**, and the draft object's `settings.rounds` independently says **20**. Reading
the field named after the quantity would have been worse than not checking at all.

Two fixture repairs the checks depend on:

- `tests/fixtures/espn_draft_detail.json` carried a **2-round trim** of the placeholder slate
  against a 16-slot roster — a genuine self-disagreement that the new check correctly rejected.
  It now carries the full **128-row** grid ESPN really serves, snaking on `pickOrder`; rows 1–16
  are byte-identical to the original capture, and `settings.size` is restored.
- `test_espn_stat_equivalence.py` built its line at 157 × 25 = 3925 exactly, so both members of
  the passing-yards pair read the same number and flipping the preference failed **zero** tests
  there. Raw is now **3944.73** — the real projection ESPN serves against those 157 buckets.
  Verified by mutation: flipping `_EQUIVALENT_STAT_IDS` now fails **2** tests in that file.

Exit codes, all three demonstrated end to end: faithful **0**, config-vs-live drift **1**,
the two derivations disagreeing **2** (`EspnDataError` caught in `main`, actionable message, no
traceback).

Suite: **492 passed, 1 xfailed**, no skips. ruff clean, pyright 0 errors.

### Injections, run against COPIES of the TOMLs in a scratch dir (committed configs untouched)

| injection | exit | names it |
|---|---|---|
| `num_teams` 8 → 9 | **1** | `num_teams config=9 live=8` |
| `draft_rounds` 16 → 17 | **1** | `draft_rounds config=17 live=16` |
| `rush_td` 6 → 7 | **1** | `rush_td[QB/RB/TE/WR] config=7.0 live=6.0` |
| `draft_slot` 8 → 2 | **0** | **NOTHING. See below.** |

---

## The seat pin has no assertion behind it. Measured, not inferred.

`config/schema.py` says of `draft_slot`: *"Live pickOrder disagreeing with it is logged loudly
rather than swallowed."* **It is not.** `service.py` has a `SEAT DRIFT` error log, and it is
**unreachable whenever a pin is set** — which is the only time it matters.

The mechanism: `CockpitService` passes its own `_slot_override` into `EspnSync`, and
`EspnSync._identity()` returns `Identity(..., self._slot_override, SOURCE_OVERRIDE)` **before**
ever consulting `teams[].owners`. So `update.identity.slot` *is* the override, and
`live != self._slot_override` can never be true.

Demonstrated offline against the committed ESPN fixture (`espn_davis_drive`, derived seat 8):

```
derived seat (no pin)   : 8  source=pick_order
pinned seat             : 2
session.slot after poll : 2  source=override
SEAT DRIFT messages     : 0
```

This is the Danger Zone failure exactly: `deployment-danger-zone.yaml` carries `--slot 6` against
a config that says `5`, added live during the draft window, and the argument won in silence.
**A gate that sets `draft_slot` to the wrong seat and expects a failure is vacuous today.**
Building that assertion is a prerequisite for trusting `draft_slot = 1` on 73131979, because seat
1 is where a wrong pin is least visible: it never has an opponent pick before its own turn to
contradict it.

**Not fixed here** — it belongs with the 73131979 config work that needs it.

---

## League A drifted again, in-season, and the new guard is what found it

`verify-scoring sleeper_boyfun`, 2026-09-05 22:2x ET — **after** its draft completed:

```
[sleeper_boyfun] SCORING DRIFT -- 7 key(s) differ (config vs live):
   idp_fum_rec        config=3.0      live=1.5
   idp_int            config=3.0      live=4.0
   idp_pass_def       config=3.0      live=2.0
   idp_qb_hit         config=1.0      live=0.0
   idp_tkl_ast        config=1.0      live=0.5
   idp_tkl_loss       config=2.0      live=1.0
   idp_tkl_solo       config=2.0      live=1.0

[sleeper_boyfun] !! STRUCTURE DRIFT -- 1 item(s) differ (config vs live).
   draft_rounds config=19     live=20
```

The commissioner roughly **halved the IDP table** (and raised `idp_int`), and the roster grew a
bench slot: `slots_bn` 7 → 8, so 12 starters + 8 bench = **20** rounds against a config that says
19. `num_teams` matched at 10 and is correctly absent from the report.

**Not corrected** — that session was forbidden from touching the committed TOMLs, and the drift
is post-draft, so it costs nothing until in-season start/sit. **Correct both before using this
league's numbers again.** This is the third recorded drift on League A; the config is now the
thing that lags, and the guard is the only reason anyone knows.

---

## `verify-actuals` does NOT exit 0 on any live ESPN league, and never did

Worth knowing before writing a gate that assumes it does. `verify-actuals espn_danger_zone` exits
**1** with `exact to the cent : 0/12`:

| pos | residual / season |
|---|---|
| QB | −0.23 to −0.28 |
| RB | −0.07 to −0.09 |
| WR | −0.04 to −0.05 |
| TE | −0.02 |

Confirmed **identical on the pre-change tree** (`git stash`, re-run, restore), so it is not a
regression. These are the documented `statId 63` residuals — offensive fumble recovered for a TD,
paid 6.0, unmapped in our vocabulary and deliberately so. K and D/ST report SKIP by design.

**So "verify-actuals exits 0, exact to the cent" is not an achievable gate as written.** The
achievable one is: every recomputable player within the `statId 63` residual, monotone in
fumbles, and no position outside it.

---

## haven: the address for a third cockpit is `192.168.1.113`

Not built — the manifests need the league key, which needs the cookies. But the address question
is settled, three ways:

1. **Cilium pool** `default-pool` is `192.168.1.100–150`; status reports `IPsTotal 51`,
   **`IPsUsed 12`**, `IPsAvailable 39`.
2. **Cluster-wide Service enumeration**: exactly **12** LoadBalancer IPs assigned — `.100`
   home-assistant, `.101` jellyfin, `.102` spoolman, `.103` headlamp, `.104` gatus, `.105`
   homepage, `.106` immich, `.107` mosquitto, `.108` frigate, `.109` alertmanager-lan, `.111`
   audible-boyfun, `.112` audible-danger-zone. The two counts agree exactly.
3. **ARP**: `.113` answers `Destination host unreachable` (nothing on the LAN claims it), while
   the live cockpit `.111` answers `Request timed out` — a claimed L2 VIP that drops ICMP. The
   probe distinguishes claimed from unclaimed.

**`ping`'s exit code is useless here** — Windows `ping` exits **0** even when the only reply is
"Destination host unreachable". Read the text, not `$?`. A first pass using the exit code reported
`.113` and `.114` as *in use*, which was exactly backwards.

**Do NOT use `.110`.** It is free in every listing and it is **stuck**: measured 2026-09-04, the
Cilium announcer never picked it up — absent from `db/show l2-announce` on all three nodes, no
`cilium-l2announce-*` lease in kube-system, while `.111` answered in ~3ms. The stuck state is
bound to the address, not the Service. Cleanup was deferred; it is still deferred.

The new Deployment models on `deployment-danger-zone.yaml` with: `secretKeyRef.name:
audible-secrets-espn2`, `--league <key>`, **no `--slot`** (the seat belongs in the TOML), and the
`podAntiAffinity` `values:` list extended to all three apps.

**`audible-secrets-espn2` is already live**, not just committed: it is on haven `main` and
appears in the `apps` Flux Kustomization's inventory as `audible_audible-secrets-espn2__Secret`.
Nothing references it yet. So the cockpit only needs the Deployment and Service.

### The Flux freeze is OFF, and pulling it again is a documented lever

PR #352 suspended `apps` for the 2026-09-05 drafts, merged 17:39 ET, and has been **reverted**.
Measured on the live cluster 2026-09-06 03:06 UTC: `apps` carries no `suspend`,
`ReconciliationSucceeded`, healthy. So a merged haven PR **will** apply.

`kubernetes/flux/config/apps.yaml` now carries the procedure in a comment block that names
**2026-09-08 as the next one**: add `suspend: true` under `dependsOn`, merge, revert afterwards.

**Blast radius, stated plainly: there is no per-app Flux Kustomization.** `apps` reconciles
`./kubernetes/apps` in its entirety, so suspending it freezes **every** app — home-assistant,
immich, frigate, mcp, vaultwarden and the rest. `infra` and `cluster` are not suspended. For one
evening that is acceptable and fully reversible; it is not a lever to leave pulled. While
suspended, merged PRs simply do not apply — nothing queues up wrong.

**Order for Tuesday:** deploy the third cockpit, `refresh-data`, container-restart to reach
`origin: disk`, and only then pull the freeze. Freezing first would block the deploy.

---

## ESPN — verified, do not re-derive

### Auth and transport

- `League(league_id, year, espn_s2, SWID)` (braces kept), read from `.env`. Read-only.
- Endpoint: `lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leagues/{id}`.
- **Not edge-cached.** `x-cache: Miss from cloudfront`, `must-revalidate`, no `age` header. Use a
  conditional GET with `If-None-Match` and **no cache-buster**; a repeat returns `304`, 0 bytes.
  **Sleeper needs a cache-buster; ESPN does not. Do not generalise either way.**

### Player pool

- `view=kona_player_info` plus an `X-Fantasy-Filter` header.
- **`sortDraftRanks` is mandatory.** Without it the endpoint returns `200` with zero players and
  no error of any kind. An empty pool raises rather than becoming an empty board.
- Pool saturates at **1,026**.

### Translation map

- **RB / WR / TE:** exact via statIds `{3, 4, 20, 19, 24, 25, 26, 42, 43, 44, 53, 72}`.
- **QB passing yards ride an EQUIVALENT PAIR** — `statId 8` (25-yard buckets) and `statId 3`
  (raw). ESPN ships **both on every line regardless of which the league pays**, so translation
  filters by `scored_stat_ids`. 6012 pays the bucket; 485267278 pays raw. Without the filter a
  quarterback is doubled; with the wrong preference he scores zero passing yards, ~160 points
  light, and still looks like a plausible QB. The bucket floors: 157 buckets = 3,925 yards of
  credit against 3,944.73 actual.
- **K and D/ST:** ESPN-native, translation incomplete — **flagged, not fixed**. Kicker misses are
  bucketed −1/−2/−3 against our flat `fgmiss`; D/ST yards-allowed tiers are unmapped.

### The specialist gap costs the board nothing. Measured, not assumed.

K and D/ST are never translated: `_pool_entries` assigns them `SOURCE_SPECIALIST` and
`player_projections` returns ESPN's own league-applied `appliedTotal`. Over all 90
specialist-sourced players: `max |board points − ESPN appliedTotal| = 0.000000`. **Expected error
0.0 pts/season, rank movement 0.**

The gap is **latent**: the yards-allowed rule is worth a mean of −16.3 pts/season across the D/ST
pool (−37.8 to +5.3). Anyone who "fixes" the vocabulary and starts translating D/ST inherits all
of it. Leave it alone. **`SPECIALIST_GAP`'s own wording still says "~15 pts/season" where the
measured board error is 0.000000** — still worth rewording.

### Ranks

`playerRankType = "STANDARD"`. Per-season ranks exist 400/400 for 2023–2025 and are **absent for
2021–2022** — sorting by a rank type that isn't there returns arbitrary order silently. STANDARD
is **not** a zero-PPR ordering: it matches PPR at the top and diverges only for non-receiving
backs (Henry STANDARD #10 / PPR #19). Anything treating it as a market baseline for a half-PPR
field will be wrong.

### Draft detail

- `view=mDraftDetail` → `draftDetail.{drafted, inProgress, picks}`.
- **Pre-draft returns a COMPLETE placeholder slate** — teams × rounds entries, every
  `playerId: -1`. Filter `playerId != -1`; use `drafted` / `inProgress` for real state. A sync
  that counts raw pick records believes the draft finished before it started. Measured: 128 rows
  for 6012 (8×16), 160 for 485267278 (10×16).
- Pick fields: `playerId`, `teamId`, `roundId`, `roundPickNumber`, `overallPickNumber`.
- `settings.draftSettings.pickOrder` is teamIds in draft-slot order — measured
  `[2, 3, 6, 4, 1, 5, 7, 8]` for 6012, **not** an identity map, so it is real commissioner-set
  data rather than a Sleeper-style placeholder. Type `SNAKE`, `orderType: MANUAL`.
- The seat is derived from `ESPN_SWID` against `teams[].owners` — **match `owners`, not just
  `primaryOwner`**: at least one team in 6012 is co-owned. No flag required. **But see the seat
  section above: a pin silently beats the derivation and nothing says so.**
- `settings.size` is the live team count and is present on both reachable leagues.
- **One request per tick.** `mDraftDetail` + `mTeam` + `mSettings` ride one conditional GET, so
  state, picks, seats, rounds and structure all come out of that single response. There is a test
  pinning this at one. `verify_structure` costs two (mSettings + the draft bundle) and is not on
  the poll path.

### The live-draft sync populates. Measured 2026-09-05, post-draft.

The standing worry was that `mDraftDetail` "never delivers a pick" — clean 304s through a whole
live draft, DDAFFL entered by hand — and that **a 304 cannot distinguish "nothing changed" from
"this never populates."** Half of that is now answered. Against the completed `espn_danger_zone`
draft:

```
call 1: etag_cached=True real_picks=160 drafted=True
call 2: etag_cached=True real_picks=160 drafted=True     <- served from the 304 path
call 3: etag_cached=True real_picks=160 drafted=True
poll 1: picks=160 status=complete rounds=16 seat=6
poll 2: picks=160 status=complete rounds=16 seat=6
```

So: **the endpoint populates** (160 real picks, not placeholders), **the 304 path preserves the
payload** rather than returning an empty draft, and **`EspnSync.poll` delivers all 160 through
the normal cockpit path**. None of those three is the fault.

**What is NOT tested, and is the whole remaining question:** whether ESPN's ETag actually
*changes* as picks land mid-draft. A server that returns a stable ETag while the body changes
would produce exactly the observed symptom — endless 304s over a draft that is filling up — and
this post-draft probe cannot see it. That is a much narrower thing to validate than "the
instrument may be fundamentally broken", and it has an obvious mitigation if it proves true:
drop the conditional request for the draft view and eat a full body every 5s.

### Danger Zone's `draft_slot` is wrong in the TOML, and the derivation says so

Same probe, no override: the seat derived from the account-1 SWID against `teams[].owners` is
**6**. `leagues/espn_danger_zone.toml` says **5**, and `deployment-danger-zone.yaml` carries
`--slot 6` — added by hand during the draft window. **The argument was right and the config is
the stale one.** Recorded, not corrected (TOMLs were out of bounds for that session). This is a
live, already-present case for the derived-vs-pinned assertion above to catch.

### Reconciliation residual

`statId 63` (offensive fumble recovered for a TD, paid 6.0) is unmapped; the config is not
changing. It is the **entire** difference between our recomputation and ESPN's `appliedTotal`.
See the `verify-actuals` section above for the per-position numbers.

### Fallback populations (6012's 1,026-player pool)

**432** scored by us from translated stat lines, **89** K/D-ST handed to ESPN by design, and
**505** offensive players taking ESPN's number — 431 project to 0.0 either way, and 74 are
return-only specialists scored on return yards this league does not pay. All three paths are
counted and printed; none can pass for a computed projection.

---

## Sleeper — verified, do not re-derive

- Projections/stats on `api.sleeper.com` (undocumented, Rotowire); league/roster/players on
  `api.sleeper.app/v1`. Never trust precomputed `pts_*` — recompute from the raw line.
- **`/picks` IS edge-cached** (Cloudflare `s-maxage=30`, measured 57s stale against a 60s pick
  timer). Every poll needs a unique cache-busting param, then an `If-None-Match` for the cheap
  304. Opposite of ESPN.
- **`settings.draft_rounds` is a KEEPER ARTIFACT** — live League A serves `3` on a twenty-slot
  roster. Rounds are `roster_positions` minus `IR`/`TAXI`.
- `draft_order` is `null` until the draft opens, so `my_slot: unresolved` pre-draft is EXPECTED.
  `slot_to_roster_id` exists pre-draft as the identity map `{1:1, …}` and **lies**: the completed
  2025 draft shows `{1:4, 2:2, 3:6, …}`. Never derive a slot from it.
- Users and rosters are not 1:1 — 9 users, 10 rosters, two with `owner_id: null`.
- ADP `999.0` means "undrafted in this market", not a real ADP.

---

## Known breakage being worked around

**nflreadpy 0.1.5 cannot reach DynastyProcess.** It hardcodes
`https://github.com/dynastyprocess/data/raw/master/files/`, and GitHub answers that path with a
404 HTML page (measured 2026-08-17: 404 with 305 KB of error page, while
`raw.githubusercontent.com/...` returns 200 with the 2.6 MB CSV). 0.1.5 is the latest release.

`adapters/nflverse.py` tries nflreadpy first and falls back to the raw host for the two affected
loaders. Primary-first means it resumes using upstream on its own once fixed; **delete the
workaround block then.** The fallback reads every column as a string on purpose — this is an ID
spine, and a `sleeper_id` inferred as a float becomes `"4034.0"` the moment anything stringifies
it, failing the join silently for every player instead of loudly for none.

**nflreadpy caches in memory only** (`CacheMode.MEMORY`). That is why the disk cache exists.

### The origin dance

`origin` is `_ORIGINS`, a **process-global** in `adapters/nflverse.py` written once per source at
load. A fresh pod reports `mixed`; `refresh-data` changes **nothing** because it runs in a
separate process; a **container** restart re-reads the surviving `emptyDir` and converges to
`disk`; a **pod roll** wipes the `emptyDir` and goes back to `mixed`. **Refresh after the last
deploy, never before.**

**Read `origin` from `/healthz`, and the league key from `/api/state`. Neither endpoint has
both.** Any check that greps one for the other's field returns empty on a healthy cockpit.

Container restart, one pod at a time (there is no shell in the image):

```bash
POD=$(kubectl -n audible get pod -l app=audible-boyfun -o jsonpath='{.items[0].metadata.name}')
kubectl -n audible exec "$POD" -- python -c "import os,signal; os.kill(1, signal.SIGTERM)"
```

Same pod name back with `restarts=1` is how you know the `emptyDir` survived.

---

## haven needs attention and it is not ours to do

- **The Renovate freeze on `ghcr.io/eyanric/**` is NOT merged — the opposite is.** PR #338 added a
  freeze; **PR #344 deleted it on 2026-09-02**. The live rule is `automerge: true,
  minimumReleaseAge: '0 days'`. A digest bump merges itself unattended and rolls the pods.
  **Restore it before 2026-09-08.**
- **The public MCP endpoint is broken.** `mcp-audible` proxies to
  `http://audible.audible.svc.cluster.local:80`, and **no Service named `audible` exists** in that
  namespace — only `audible-boyfun` and `audible-danger-zone`. The proxy is Ready because its
  probes are TCP against its own port. This is why the `audible-mcp` connector 502s, and it still
  502s as of 2026-09-05.

---

## Standing decisions

- **`leagues/*.toml` does not change** to chase a *translation* gap. Flag it here instead. (A
  live-vs-config **drift** is the opposite: live wins and the config changes.)
- **Manual picks are real picks** — numbered, attributed, and they advance the clock.
  Indistinguishable downstream from synced picks, including `_recent_picks` and the run window,
  both of which read `effective_picks()`.
- **Never invent a draft slot.** Unresolved is an explicit state; `slot = 0` meant "me" and
  silently attributed the whole room to one roster. Both platforms derive the seat and return
  `None` with source `unresolved` when they cannot.
- **One poll loop, one `DraftSession`.** Everything platform-shaped lives behind
  `DraftSync.poll(draft_id, want_meta=, slot_locked=) -> DraftUpdate`. `DraftUpdate` uses `None`
  for "unchanged": a poll that only fetched picks must not blank the draft status it never asked
  about.
- **ESPN picks arrive in ESPN's id space; the board is in Sleeper's.** `EspnIdBridge` translates
  via the Sleeper catalog's `espn_id`. An id that will not translate keeps its ESPN value rather
  than being dropped — the pick really happened — and those are counted and logged.
- **Consensus is the projection of record.** The opportunity model lost out-of-sample at every
  position; it rides as a flag overlay, never as a multiplier.
- **`value_metric = "vorp"`**, not scarcity/VONA — VONA edged it in backtest (+28 vs +24) but the
  current implementation has a junk-tail pathology on flat positions producing a QB-dominated
  board.
- **Nothing new enters the sort.** `draft/usage.py` is imported by the state builder and the MCP
  surface, never `board.py`, `value/` or `scoring/`. The `usage_in_sort` mutation reorders the
  board by target share while keeping ranks a clean 1..N, and only that check catches it.
- No model calls inside `audible`, ever. No writes to any platform.

---

## Method that transferred, from three completed drafts

### Board vs its own market — measure it per league, carry no rule across

Board rank of the first player at each position against that league's own ADP market. Positive
means the board wants him earlier than the market takes him — the direction that costs picks.

`sleeper_boyfun` needed a read-past rule: **DEF +21.3 rounds, K +12.9, LB +6.8**.
`espn_danger_zone` needed **none** — every specialist delta negative (K −3.4, DEF −2.8, QB −4.1).
Same engine, opposite answers, because `replacement_bench_slots = 7` there and `0` in League A.

**So measure it for 73131979 and state which it is. Do not carry either league's rule.**
Specialists never enter the bench allocation at all (`_startable_slots(config, pos) >= 2` gates
them out), so `replacement_bench_slots` cannot fix a League-A-shaped inflation.

**The QB junk-tail pathology has not returned.** Pre-registered stop condition was ≥8 QBs inside
the board's top 15. Measured: **1** in League A, **0** in Danger Zone.

### In an 8-team league, zero kickers and defences go in the first 128 picks

Measured on DDAFFL. In the 10-team Danger Zone the first DEF goes at 88 and the first K at 93, and
10 DEF / 9 K are gone by 160. 73131979 is 8-team, so expect the DDAFFL shape.

### `recommend` has no notion of roster balance — still true, still not fixed

**Draft-night rule:** `recommend` returns five rows — read all five, not the first. When you
already hold three startable bodies at a position, take the best row that is not that position.
The dry run produced **10 WR, 2 RB, 1 TE, 1 QB, 1 DEF, 1 K**. Deliberately not patched — the right
fix is marginal value against my own roster, which changes what the board recommends.

Its bye-week consequence, measured: a legal lineup does not exist in every week, structurally,
because `RB` slots take only `RB` and the roster held exactly two.

### Opportunity cost shipped, and `survival()` did not

`recommend` answers "who is best **among those who will not survive to my next turn?**" using
`survives_by = ADP − next_pick`, shown as that subtraction. It does **not** call
`live.survival()`, which divides by `opponent_picks_until_horizon`.

**`survival()` goes quiet at back-to-back turns and 73131979 is the worst case for it.** Seat 1 of
8 picks in PAIRS — **1, 16/17, 32/33, 48/49** — so `opponent_picks` is 0 at every turn after the
first and it returns 1.0 for everyone at exactly the moment two picks are on the clock.
`draft/urgency.py` bypasses it with visible subtraction rather than fixing it. **Fix or delete
it** — but it is separate work from onboarding the league.

`ADP` is the primary quantity because it has full coverage: **ESPN's displayed rank covers only 57
of the board's top 200 (28%)**, and Sleeper publishes no displayed rank at all. Every QB, TE, K
and DEF figure is marked `survival_confidence: "low"` — ADP does not predict points there.

### Reach annotation: attempted twice, failed twice, not built

R1 fired on `value_rank − current_pick ≥ 40`: 12 firings against a ceiling of 8, six of them
quarterbacks. R2 dropped the VORP term for `market_rank − current_pick` and **failed its
pre-registered sensitivity gate at −3**; 13 of its 15 firings were kickers and defences, below the
ADP noise floor, leaving **two picks** of honest unmarked signal over a 128-pick draft.

**The headline: DDAFFL's "worst pick" was never a reach.** Joe Burrow's `adp_half_ppr` is 54.5; he
was taken at 57, *after* the market had him. R1's famous "+52" was `vorp_rank(109) − pick(57)` — a
statement about where this board ranks QBs in a 1-QB league, not about the pick being early.

**Do not re-attempt** without answering: is there any position in either league where the ADP
market both carries signal (RB and WR only) *and* is disagreed with often enough to be worth a
column? On this evidence, no.

### Data enrichment: what shipped, what was refused

Six usage numbers per player (target share, air-yards share, route participation, snap share,
depth-chart slot, 2026 bye) are in `_slim()`, so **the MCP surface carries them**. They are not
board columns. **Route participation is a PROXY** — share of the team's charted-route plays he was
on the field for; a TE who stays in to block counts. Validated 2025: Jefferson 95.6%, Chase 91.5%,
McBride 94.0%, Henry 39.5%.

Cache is **derived-and-pinned, not raw**: `route_participation_2025` (978 rows, 14 KB) and
`depth_chart_slots_2026` (3,182 rows, 20 KB) rather than 45k and 472k raw rows.

**LA vs LAR.** nflverse schedules spell the Rams `LA`; the board says `LAR`. Only the measured
difference is mapped — a first fix also mapped plausible historical aliases and broke Washington,
where both sides already said `WAS`.

**Sleeper ADP fallback REFUSED, measured not assumed.** `survival_pct` is None wherever
`adp_known` is false, so unpriced players are invisible to scarcity. The mechanism is real; the
magnitude is not: of the whole 3,302-row board, 2,229 are unpriced (67.5%) — but **0 of the top
128**, 1 of the top 300. Every player reachable in 8×16 picks already has ESPN ADP. **Re-measure
if 73131979 is ever served past ~rank 250.**

---

## Open / next

**Ordered by what breaks Tuesday's draft, not by what is interesting.**

1. **Swap `.env` to the second ESPN account's cookies.** Manual, browser session cookies, no API
   mints them. **Nothing below that names 73131979 can start until this happens.** The per-league
   cookie source that would remove this step (constructor params already exist on `EspnAdapter`;
   no CLI path passes them) is a real improvement and worth building once the draft is done.
2. **Onboard 73131979**: derive the key from the live league name, write
   `leagues/espn_<key>.toml`, run the verify loop until faithful. **Derive** the seat and assert
   it equals 1 rather than pinning what Eric said. Measure the specialist read-past deltas and
   state which league this is.
3. **Build the derived-vs-pinned seat assertion** — see above. It is a prerequisite for trusting
   `draft_slot = 1`, and today it does not exist.
4. **haven: a third cockpit** — `deployment-<key>.yaml` + `service-<key>.yaml` on
   **192.168.1.113**, `audible-secrets-espn2`, no `--slot`, anti-affinity extended to three.
5. **haven: freeze `apps` for Tuesday evening** — the lever and its blast radius are documented
   in `kubernetes/flux/config/apps.yaml`, which names 2026-09-08 by date. Pull it AFTER the
   cockpit is deployed and refreshed, not before. Restoring the Renovate freeze on
   `ghcr.io/eyanric/**` is the narrower belt-and-braces version.
6. **ESPN live-draft sync: the ambiguity is now HALF resolved, and the risk is smaller than it
   looked.** See the measurement below. What is still untested is narrow and specific.
7. **A pre-flight session Tuesday afternoon** that enumerates every external input the cockpit
   needs and asserts each resolves, exiting non-zero on any UNRESOLVED.
8. **Correct League A's config**: 7 IDP weights and `draft_rounds` 19 → 20. Only matters in-season
   now, but the guard will keep shouting until it is done.
9. **haven: point `mcp-audible` at a Service that exists.** The public MCP surface is down.
10. **`survival()` goes quiet at back-to-back turns** — seat 1 of 8 is the worst case. Fix or
    delete it.
11. **`recommend` has no notion of roster balance** — read all five rows until there is a fix.
12. **`SPECIALIST_GAP` says "~15 pts/season" where the measured error is 0.000000.** Reword.
13. **`median_match` vs live `league_average_match: 0`** — decide and either correct or delete the
    field. Touches one CLI print line and no number.
