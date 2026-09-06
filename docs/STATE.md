# audible — carry-forward state

**Read this first. Rewrite it as your final commit.**

This file exists because the previous carry-forward lived outside the repo, so the session that
needed to update it could not reach it. Everything a new session needs to avoid re-deriving
settled facts belongs here, in the repo, versioned with the code it describes.

Rules for editing:

- **Verified facts only.** If it was measured against a live API, say so and give the number.
- **Record the decision, not just the finding.** "Flagged not fixed" is the useful half.
- **Delete what stops being true.** A stale line here is worse than no line.

Last rewritten **2026-09-06, 00:30 ET**, after 73131979 was onboarded and the seat and
account checks were built.

---

## THE ONLY DRAFT LEFT IS NOW READABLE, CONFIGURED, AND SERVED

**ESPN league `73131979` = "Green Hope Dog Walkers". Tuesday 2026-09-08, 19:00 ET. Snake,
8 teams, 16 rounds, seat 1.** Config is `leagues/espn_green_hope.toml`; the cockpit manifests
are in haven on `feat/audible-cockpit-green-hope`.

It lives on a **SECOND ESPN account**, and the two accounts are strictly disjoint. Measured
2026-09-05/06, both directions:

| league | account 1 cookies | account 2 cookies |
|---|---|---|
| `6012` | **200** | **401** |
| `485267278` | **200** | **401** |
| `73131979` | **401** | **200** |
| `999999999999` (control) | 400 | 400 |

The control matters: a bad id returns **400**, so a 401 means the league exists and is private.

**The blocker is gone, and not by swapping cookies.** `LeagueConfig` now names the environment
keys a league reads -- `espn_swid_env` / `espn_s2_env`, defaulting to the historical
`ESPN_SWID` / `ESPN_S2` -- and `EspnAdapter.for_league(config)` threads them to all nine
construction sites. Both accounts sit in `.env` at once and **one process serves either**.

Verified with no shell variables set, in one process tree:

```
verify-scoring espn_davis_drive  -> FAITHFUL, exit 0     (account 1)
verify-scoring espn_green_hope   -> FAITHFUL, exit 0     (account 2)
```

**Do not go back to exporting cookies into a shell.** That gave one process one account, so
every other league 401'd for as long as the shell lived.

`.env` key names, confirmed by reading (a previous session reported `ESPN_S`, and was wrong --
nothing was renamed): `ESPN_SWID`, `ESPN_S2`, `ESPN_SWID_ESPN2`, `ESPN_S2_ESPN2`,
`ANTHROPIC_API_KEY`, `MCP_AUTH_TOKEN`. `ANTHROPIC_API_KEY` is vestigial **and empty**;
`.env.example` says outright there will never be one. Left alone.

---

## The leagues

| key | platform / id | shape | market | cockpit | draft |
|---|---|---|---|---|---|
| `sleeper_boyfun` | Sleeper `1361543954771738624` | 10-team, half-PPR, SUPERFLEX, IDP | `adp_idp` | 192.168.1.111 | **complete** |
| `espn_danger_zone` | ESPN `485267278` | 10-team, full PPR every position, 16 rounds | `adp_ppr` | 192.168.1.112 | **complete** (160 picks) |
| `espn_davis_drive` | ESPN `6012` | 8-team, 1-QB, half-PPR WR/TE, 0.0 RB | `adp_half_ppr` | none | **complete** (128 picks) |
| `espn_green_hope` | ESPN `73131979` | 8-team, 16 rounds, 1-QB, **STANDARD (zero PPR)** | `adp_std` | **192.168.1.113 (PR open)** | **2026-09-08 19:00** |

The first three report `drafted: true` / status `complete` as of 2026-09-05 22:29 ET; their
draft-night rules below are **historical**, kept for method. `espn_green_hope` is `pre_draft`
and is the only live one.

`espn_green_hope` is the only league here on the second ESPN account, and the only one that
sets `espn_swid_env` / `espn_s2_env`. It is also the only **zero-PPR** league: `statId 53`
is absent from its live scoring items entirely, so no position is paid for a catch. It pays
**six-point passing TDs** and **raw** passing yards (`statId 3`), not the 25-yard bucket.

---

## What shipped 2026-09-06: the seat and the account became checkable

Both were the same bug -- a value that could only ever agree with itself, so the check written
to catch a disagreement could never fire.

### Per-league cookie source

`LeagueConfig` gained `espn_swid_env` / `espn_s2_env`. `EspnAdapter.for_league(config)` is the
constructor every caller with a league now uses; all nine non-test construction sites were
already holding a config, so nothing had to be re-plumbed.

`for_league` passes the key **NAMES**, not resolved values, and that is load-bearing:
`__init__`'s `swid=None` means "fall back to the default key", so resolving in the factory
would silently serve the **default account** exactly when the named key is missing. There is a
test pinning that.

A 401 now names the league and the two env keys it read. "Wrong account" and "expired session"
are different problems and ESPN answers both with a bare 401; a generic "re-pull your cookies"
sends you to re-copy credentials that were never the problem.

### The derived-vs-pinned seat assertion, which did not exist

`EspnSync._identity` returned the override **before** reading `teams[].owners`, so
`CockpitService`'s SEAT DRIFT error compared the override with itself. Unreachable on every
league that pins a seat -- the only ones that need it.

The derivation now runs unconditionally on **both** platforms. `Identity` carries
`derived_slot` beside `slot`: the pin still wins (that is its job) while the platform's own
answer survives to be compared, via `Identity.seat_conflict`.

**The load-bearing part is that it reaches a person.** `verify_structure` now reports a
`draft_slot` row, so a wrong pin is a **non-zero exit from `verify-scoring`**, not a log line.
It fires on the live Danger Zone case today:

```
[espn_danger_zone] !! STRUCTURE DRIFT -- 1 item(s) differ (config vs live).
   draft_slot   config=5      live=6
EXIT=1
```

**That means `verify-scoring espn_danger_zone` is RED until someone fixes that TOML.** It was
green only because nothing checked. Danger Zone's `draft_slot` and `deployment-danger-zone.yaml`'s
hand-added `--slot 6` were out of bounds for this session; the argument is right and the config
is stale. No automation runs this command -- the `audible-sync-watchdog` CronJob calls haven's
`verify-audible-league.sh`, which does not.

### Absent and zero are the same claim

`verify_scoring` reported drift whenever **either** side merely lacked a key, so a league with
no PPR produced four rows saying "neither of us pays this". That is how four real drifts hid
inside seventy-eight on League A. Now only a value that is **present and different** is drift;
a stat ESPN does not list and a config key that is absent both read as 0.0. `cfg=0.5, live=absent`
is still drift. The same rule was applied to the reception guard, which called "unscored live"
a mismatch against a config that expects 0.0.

### Suite

**501 passed, 1 xfailed** (was 492 + 1; +9 new). ruff clean, pyright 0 errors. The new tests
are load-bearing: reverting `_identity` to the old short-circuit fails exactly the two that
assert the new behaviour.

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

## The seat pin, and the one case still open

The assertion exists now -- see "What shipped 2026-09-06" above. What remains is the case it
found and was not allowed to fix:

**`leagues/espn_danger_zone.toml` says `draft_slot = 5`; the SWID-derived seat is 6; and
`deployment-danger-zone.yaml` carries a hand-added `--slot 6`.** The argument is right and the
config is stale. `verify-scoring espn_danger_zone` exits 1 on it today. Fixing the TOML and
dropping the `--slot` argument belongs to Eric -- a seat pinned in two places will disagree
again.

Seat 1 of 8, which is what `espn_green_hope` pins, is where a wrong pin is **least** visible:
it never has an opponent pick before its own turn to contradict it. That is exactly why the
seat there was derived (teamId 2, `pickOrder [2,9,6,7,4,1,5,8]` -> seat 1) rather than taken
on trust, and why it is asserted rather than assumed.

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

## `verify-actuals`: exit code depends on the BASIS, not on the league

**The previous claim here -- "does NOT exit 0 on any live ESPN league, and never did" -- was
over-broad and is corrected.** It generalised from one league. Measured 2026-09-06:

| league | basis | exact to the cent | exit |
|---|---|---|---|
| `espn_green_hope` | **actuals** | **12/12** | **0** |
| `espn_davis_drive` | **actuals** | **12/12** | **0** |
| `espn_danger_zone` | projections | 0/12 | 1 |

The split is **actuals vs projections**, and the mechanism is `statId 63` -- an offensive
fumble recovered for a touchdown, paid 6.0, unmapped in our vocabulary and deliberately so.

* **Projections** carry it as a FRACTIONAL expected value on nearly every line, so every
  recomputable player is a little light. Danger Zone did not exist in 2025 and so has no
  actuals; that is why it falls to projections. Per-season residual: QB −0.23 to −0.28,
  RB −0.07 to −0.09, WR −0.04 to −0.05, TE −0.02.
* **Actuals** are integers -- a player either recovered a fumble for a touchdown or did not.
  Measured over the whole 2025 actual corpus for 73131979: **1,091 players, exactly ONE
  carries a `statId 63` key at all** (Woody Marks, RB, value 1, worth exactly 6.00 points).
  None of the twelve sampled players carries one, so the residual is 0.00 and the command
  exits 0.

So the mechanism is real, quantified, and simply does not touch this league's sample. K and
D/ST report SKIP by design in every case.

## haven: the third cockpit is written and PR'd on `192.168.1.113`

`kubernetes/apps/audible/deployment-green-hope.yaml` + `service-green-hope.yaml`, added to
`kustomization.yaml`, on branch `feat/audible-cockpit-green-hope`. **Not merged.**

`.113` was **re-confirmed against the live cluster immediately before committing**: a
cluster-wide enumeration returns exactly twelve assigned LoadBalancer addresses -- `.100`
home-assistant, `.101` jellyfin, `.102` spoolman, `.103` headlamp, `.104` gatus, `.105`
homepage, `.106` immich, `.107` mosquitto, `.108` frigate, `.109` alertmanager-lan, `.111`
audible-boyfun, `.112` audible-danger-zone -- agreeing with the Cilium pool's own `IPsUsed 12`.
`.113` is not among them.

**Do NOT use `.110`.** Free in every listing and **stuck**: measured 2026-09-04 the Cilium
announcer never picked it up (absent from `db/show l2-announce` on all three nodes, no
`cilium-l2announce-*` lease) while `.111` answered in ~3ms. Bound to the address, not the
Service. Cleanup still deferred.

**`ping`'s exit code is useless here** -- Windows `ping` exits 0 even when the only reply is
"Destination host unreachable". Read the text, not `$?`.

The Deployment: `secretKeyRef.name: audible-secrets-espn2`, `--league espn_green_hope`, and
**no `--slot`** (the seat lives in the TOML, and putting it in two places is what went wrong
on Danger Zone).

### The Kubernetes side is NOT unaffected by the per-league cookie keys. Two real bugs.

Both were caught by an adversarial review of the manifest, after it was already committed and
PR'd. Recording them because the first one refutes a premise that was stated as settled.

**1. The container must export the names the CONFIG asks for, not `ESPN_SWID` / `ESPN_S2`.**

The claim "each pod gets its own Secret via `secretKeyRef`, so the variable names stay
`ESPN_SWID` / `ESPN_S2` inside every container" **stops being true the moment a league names
non-default keys** -- which is exactly what `espn_green_hope.toml` does.
`EspnAdapter.for_league` reads the names the CONFIG gives it, and there is deliberately **no
fallback** to the defaults, because falling back is how a process silently serves the wrong
account. `.dockerignore` excludes `.env`, so there is no file to fall back to either.

As first written, that pod would have started, built a correct board, reported `ok:true` -- and
been attached to no draft. Proved by simulating the container (dotenv stubbed empty, only the
injected variables present):

```
container exports ESPN_SWID / ESPN_S2 ............ cookies resolve: False
  -> EspnAuthError: ESPN credentials missing for [espn_green_hope]
     (league 73131979): set ESPN_SWID_ESPN2 ...
container exports ESPN_SWID_ESPN2 / ESPN_S2_ESPN2  cookies resolve: True
```

The SECRET KEYS are unchanged -- `audible-secrets-espn2` still holds `ESPN_SWID` / `ESPN_S2`.
Only the exported variable names differ, via `name:`. **The Deployment and the TOML now have to
agree; change one and you must change the other.**

**2. The image bakes the league configs in, so the digest must be repinned.** The Dockerfile
does `COPY leagues/ ./leagues/`. A digest built before `leagues/espn_green_hope.toml` existed
has no such league, and `serve --league espn_green_hope` exits 1 -> CrashLoopBackOff (confirmed:
`_load` raises `SystemExit` on an unknown key). Order: merge the audible PR, let its `image`
workflow publish (it watches `leagues/**`), take the digest from the job summary, repin, merge
haven. Renovate would get there unattended; that is not a plan on draft day.

**3. Minor, same review:** `MCP_AUTH_TOKEN` now reads `audible-secrets-espn2` rather than
`audible-secrets`. Neither Secret defines that key, but `reloader.stakater.com/auto` collects
the Secret NAMES a pod references, not the keys it finds -- so referencing `audible-secrets`
would let a rotation of ACCOUNT 1's cookies roll the green-hope pod and wipe the warm
`emptyDir` board of the one league actually drafting.

**The anti-affinity was extended in the NEW FILE ONLY.** It lists all three app names, so the
new pod avoids nodes already running either existing cockpit -- which is what matters, since it
is the only one being scheduled. The two existing Deployments still list two values each.
Editing them was out of bounds this session, and doing so would roll both live cockpits and
wipe their warm `emptyDir` boards for no scheduling gain. Measured: the two live pods are
already on different nodes (`talos-y0w-bvm`, `talos-lt1-mgf`).

Validation run before commit: `yamllint` clean, `kubectl kustomize` builds 9 resources,
`kubectl apply --dry-run=server` creates both. The dry-run emits a **PodSecurity
`restricted:latest` warning** (allowPrivilegeEscalation, capabilities, seccompProfile) -- it is
**pre-existing and identical on `deployment-danger-zone.yaml`**, the `audible` namespace carries
no PodSecurity enforcement labels, and both live pods are Running. Not introduced here, and not
fixed here.

**`audible-secrets-espn2` is already live** on haven `main` and in the `apps` Kustomization's
inventory. It defines exactly `ESPN_SWID` and `ESPN_S2` -- no `MCP_AUTH_TOKEN`, which is why
the new Deployment reads that key from `audible-secrets` with `optional: true`, exactly as the
other two do.

### The Flux freeze is OFF, and pulling it again is a documented lever

Confirmed on this branch 2026-09-06: `kubernetes/flux/config/apps.yaml` carries no `suspend`
key, only the procedure in comments. PR #373 lifted the draft-weekend freeze. So a merged haven
PR **will** apply.

(A mapping agent reported the freeze as ON during this session. It had read `/c/dev/haven-freeze`,
a stale sibling worktree. Check which directory you are in.)

**Blast radius, stated plainly: there is no per-app Flux Kustomization.** `apps` reconciles
`./kubernetes/apps` in its entirety, so suspending it freezes **every** app. `infra` and
`cluster` are not suspended. Fully reversible; not a lever to leave pulled.

**Order for Tuesday:** deploy the third cockpit, `refresh-data`, container-restart to reach
`origin: disk`, and only then pull the freeze. Freezing first would block the deploy.

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

### Danger Zone's `draft_slot` is wrong in the TOML, and the guard now SAYS so

Same probe, no override: the seat derived from the account-1 SWID against `teams[].owners` is
**6**. `leagues/espn_danger_zone.toml` says **5**, and `deployment-danger-zone.yaml` carries
`--slot 6`, added by hand during the draft window. **The argument was right and the config is
the stale one.**

As of 2026-09-06 this is no longer merely recorded: `verify-scoring espn_danger_zone` exits 1
with `draft_slot config=5 live=6`. Correcting the TOML and dropping the `--slot` argument is
Eric's -- both were out of bounds this session.

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

Measured 2026-09-06 by ONE method across all three, so the numbers are comparable
(`delta_rounds = (market ADP rank − board rank) / num_teams`):

| league | market | first K | first DEF |
|---|---|---|---|
| `sleeper_boyfun` | `adp_idp` | board 83 vs adp 212 = **+12.9** | board 74 vs adp 287 = **+21.3** |
| `espn_danger_zone` | `adp_ppr` | board 127 vs adp 93 = **−3.4** | board 116 vs adp 88 = **−2.8** |
| **`espn_green_hope`** | `adp_std` | board 98 vs adp 121 = **+2.9** | board 92 vs adp 123 = **+3.9** |

Re-running the two historical leagues reproduced their recorded numbers exactly, which is what
makes the third row comparable rather than merely similar.

**`espn_green_hope` needs a MILD read-past rule: about 3 rounds on K and 4 on DEF.** It sits
between the two and much closer to Danger Zone — roughly a fifth of League A's inflation, and
opposite in sign to Danger Zone's. Practically: the board wants a kicker around pick 98 and a
defence around 92; its market does not take them until ~121 and ~123. **Read past both until
the last two rounds.** Do not carry League A's rule — four to seven times too big here — and do
not assume Danger Zone's "no rule needed" either.

Board composition of the top 128 (the whole 8 × 16 draft): RB 53, WR 35, TE 18, QB 8, K 8,
DEF 6. The RB weight is the zero-PPR shape showing up, not a pathology — receptions pay nothing
here, so WR points compress while RB replacement sits deep (rank 53 at 66.3 points against WR
rank 36 at 120.1).

Specialists never enter the bench allocation at all (`_startable_slots(config, pos) >= 2` gates
them out), so `replacement_bench_slots` cannot fix a League-A-shaped inflation.

**The QB junk-tail pathology has not returned.** Pre-registered stop condition was ≥8 QBs
inside the board's top 15. Measured: **1** in League A, **0** in Danger Zone, **0** in Green
Hope — whose top 15 is entirely running backs.

### In an 8-team league, zero kickers and defences go in the first 128 picks

Measured on DDAFFL. In the 10-team Danger Zone the first DEF goes at 88 and the first K at 93, and
10 DEF / 9 K are gone by 160.

For 73131979, its own market (`adp_std`) prices the first K at rank 121 and the first DEF
at 123 — both inside 128, unlike DDAFFL's 131/132 in `adp_half_ppr`. Close to the boundary
either way; the read-past deltas above are the number to act on.

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

Items 1-4 of the previous list are DONE: the per-league cookie source, the 73131979 config,
the derived-vs-pinned seat assertion, and the haven cockpit manifests (PR open, not merged).

1. **Merge both PRs, IN ORDER, with a digest repin between them.** audible
   `feat/onboard-green-hope-dog-walkers` first (merge-commit), which triggers its `image`
   workflow; take the digest from that job summary and put it in
   `deployment-green-hope.yaml`; then merge haven `feat/audible-cockpit-green-hope`
   (squash). **Merging haven first or without the repin gives a CrashLoopBackOff**, because
   the league TOMLs are baked into the image. Nothing reaches the cluster until haven lands.
2. **Validate whether ESPN's ETag advances as picks land. THE LARGEST REMAINING RISK to
   Tuesday.** The endpoint, the conditional request and `EspnSync.poll` are each fine -- 160
   real picks come back through the 304 path on the completed Danger Zone draft. But a server
   returning a STABLE ETag over a CHANGING body produces the observed "clean 304s all night"
   symptom exactly, and a post-draft probe cannot see it. Mitigation is cheap and known: drop
   the conditional request for the draft view and eat a full body every 5s. **Decide this
   before Tuesday**, not during.
3. **Order of operations on Tuesday, and it is not the obvious one.** Deploy the cockpit
   FIRST, then `refresh-data espn_green_hope`, then restart the CONTAINER in place to reach
   `origin: disk`, and only THEN pull the Flux freeze. Refreshing before the last deploy is
   wasted -- a pod roll wipes the `emptyDir` and returns origin to `mixed`. Freezing first
   would block the deploy.
4. **A pre-flight session Tuesday afternoon** that enumerates every external input the cockpit
   needs and asserts each resolves, exiting non-zero on any UNRESOLVED. `verify-scoring
   espn_green_hope` is most of it and exits 0 today.
5. **haven: freeze `apps` for Tuesday evening.** The lever and its blast radius are documented
   in `kubernetes/flux/config/apps.yaml`, which names 2026-09-08 by date. Pull it AFTER the
   cockpit is deployed and refreshed. Restoring the Renovate freeze on `ghcr.io/eyanric/**` is
   the narrower belt-and-braces version -- PR #344 deleted it and the live rule is
   `automerge: true, minimumReleaseAge: '0 days'`, so a digest bump merges itself and rolls the
   pods unattended.
6. **Correct `espn_danger_zone.toml`: `draft_slot` 5 -> 6, and drop `--slot 6` from
   `deployment-danger-zone.yaml`.** `verify-scoring espn_danger_zone` is RED until this is
   done -- correctly, and for the first time. A seat pinned in two places will disagree again.
7. **Correct League A's config**: 7 IDP weights and `draft_rounds` 19 -> 20. In-season only
   now, but the guard keeps shouting.
8. **`survival()` goes quiet at back-to-back turns, and seat 1 of 8 is its worst case.**
   73131979 picks in PAIRS -- 1, 16/17, 32/33, 48/49 -- so `opponent_picks_until_horizon` is 0
   at every turn after the first and `survival()` returns 1.0 for everyone at exactly the
   moment two picks are on the clock. `draft/urgency.py` bypasses it with visible ADP
   subtraction, so nothing on Tuesday depends on it. **Fix or delete it** -- separate work,
   deliberately not touched here.
9. **`recommend` has no notion of roster balance, and seat 1 of 8 hits that too.** It returns
   five rows; read all five. When you already hold three startable bodies at a position, take
   the best row that is not that position. Deliberately not patched -- the right fix is
   marginal value against my own roster, which changes what the board recommends.
10. **Read past K and DEF for about 3-4 rounds in 73131979.** Measured, mild, and specific to
    this league; see the read-past table above. Not a code change.
11. **haven: point `mcp-audible` at a Service that exists.** It proxies to
    `audible.audible.svc.cluster.local:80` and no Service named `audible` exists -- only the
    three per-league ones. This is why the `audible-mcp` connector 502s, and it still did on
    2026-09-06.
12. **`SPECIALIST_GAP` says "~15 pts/season" where the measured board error is 0.000000.**
    Reword. It prints on every `verify-scoring` run, including the green ones.
13. **`median_match` vs live `league_average_match: 0`** -- decide and either correct or delete
    the field. Touches one CLI print line and no number.
