# Draft day runbook — League B (ESPN)

**Sunday 30 August, ~19:00. ESPN league 6012. You are team 8, draft slot 8.**

One operator, one night, no second chance. Follow this while distracted.

**The one thing to remember:** every failure below ends somewhere you can still draft.
If you are lost, jump to [Fallback ladder](#fallback-ladder) and work down it.

**If it is kickoff, something is down, and all you have is the phone:** go straight to
[The endpoint is down and you are holding your phone](#the-endpoint-is-down-and-you-are-holding-your-phone).
That page is the whole procedure, in order, and it starts by telling you what is actually
broken.

> **Manual entry is the primary input until proven otherwise.**
> The sync latency against ESPN has never been measured — the temp-league draft that would
> measure it was never run. Until that number exists, treat the sync indicator as
> *informational* and enter picks by hand. Loosen this only if the measurement comes back
> under ~15s. See [Latency](#if-latency-gets-measured).

`audible` never writes to ESPN or Sleeper. Two copies can run at once without conflicting,
which is why failover is just opening a different URL.

**League A (`sleeper_boyfun`) is a different runbook.** This one is League B only. Where they
differ is called out; the biggest is that **`audible live` does not work for League B.**

---

## T-24h — Saturday 29th, evening

Run these the day before, not on the day. **This is also the freeze:** after these checks,
no merges, no rebuilds, no config edits.

```bash
# 1. Did the league change under us? It did once already, in July, on League A.
uv run audible verify-scoring espn_davis_drive
```

Expect **three** things, all of which must pass:

| line | expected |
|---|---|
| scoring | `FAITHFUL ... 48 position-scoped weights match` |
| receptions | `confirmed LIVE at 0.5/rec for WR/TE (RB stays 0.0 by design)` |
| roster structure | `FAITHFUL (9 starting slots match)` |

The RB line saying `0.0` is **correct and deliberate** — the commissioner pays running backs
nothing per reception. It is not drift. Roster drift is the one that invalidates everything:
replacement baselines derive from roster structure, so a mismatch there makes every VORP
number on the board wrong.

```bash
# 2. Fill the offline cache. THIS is the network-dependent step, and the only one.
uv run audible refresh-data
```

Expect both leagues to rebuild (~3,300 and ~7,621 players) and a list of nflverse sources on
disk. **Do this even if nothing looks broken** — nflreadpy caches in memory only, so a
container that restarts on the night re-downloads everything unless this cache is warm, and
one of its upstream URLs already 404'd once this month.

```bash
# 3. Print the paper board. It costs nothing and it is the floor of the ladder.
uv run audible cheatsheet espn_davis_drive
```

**There is no image on the laptop path any more.** `scripts/draft-day.cmd` runs
`uv run audible serve --host 127.0.0.1 --port 8080 --league espn_davis_drive` straight from
this repo — no Docker, no digest, no pull. (This section used to say the launcher "points at
an explicit digest, `sha256:d3cdb2a1…`". It does not, and has not since the launcher went
source-based.) **The version on this machine is `git log -1`.** Digests govern the CLUSTER
only; see [Fallback ladder](#fallback-ladder) rung 5.

Renovate IS frozen for the week, but for the cluster rather than the laptop:
`ghcr.io/eyanric/audible` digest automerge is disabled in `haven`'s `renovate.json5` through
**2026-08-31**, with CI failing after that date until the rule is removed.

> **`scripts/verify-offline.cmd` cannot run as written.** It is a Docker-path artifact: it
> pins `sha256:d3cdb2a1…` and its own header says to run it "AFTER draft-day.cmd has pulled
> the image at least once" — which never happens now, because the launcher pulls nothing.
> Docker Desktop was not even running on the drafting machine when this was checked
> (2026-08-28). The offline property on the laptop is instead evidenced by `/healthz`
> reporting `data.origin: "disk"`, measured below.

That script pulls the pinned digest, fills the cache volume *using that same image*, then
rebuilds both boards with `--network none`. It is a good check **of the cluster artifact**,
and it is the check most likely to catch a packaging difference. It is not a check of what
the laptop runs, because the laptop no longer runs an image at all.

It prints **PASS** or **FAIL**. **Do not pin a digest that prints FAIL.**

**Start the local cockpit and confirm it is running offline-capable:**

```bash
curl localhost:8080/healthz
```

You are looking for **three** fields:

```json
{"ok": true, "players": 3300, "data": {"origin": "disk", ...}}
```

- `ok: true` and a non-zero `players` — the board built.
- **`data.origin: "disk"`** — the board came from the cache, not the network.

  **This check applies to the LOCAL cockpit only.** Locally it is real and it passes:
  measured 2026-08-28, `from_disk: 5, from_network: 0, origin: "disk"`.

  **On the cluster (`192.168.1.110`) `mixed` is the correct, permanent answer** and no
  amount of `refresh-data` will change it — see
  [the cluster has no disk guarantee](#the-cluster-has-no-disk-guarantee-and-cannot-have-one-here).
  Do not go looking for an unmounted volume there; the volume is mounted and is working
  exactly as designed.

A 503 means the board is not built — read `message` on `/api/state`, it says what it is
waiting on.

---

## T-30m — Sunday 18:30

1. **Start the local cockpit** — double-click `scripts/draft-day.cmd`. (It is a process in
   its own window, not a container; closing that window stops the cockpit.)
2. **Confirm the draft was found.** On `/healthz`, `draft_id` should read `6012`. For ESPN the
   league *is* the draft; there is no separate draft id to rediscover.
3. **Confirm picks read `0`, not `128`.** Pre-draft, ESPN serves a complete 128-entry
   placeholder slate with `playerId: -1`. A `picks` count of 128 before anyone has drafted
   means the filter has broken and the board thinks the draft is over. This is the single
   most important pre-draft check.
4. **Confirm your slot.** In `/api/state`, `clock.my_slot` should be `8` and
   `clock.my_slot_source` should read `pick_order`. It is derived from your `ESPN_SWID`
   cookie against the team owners — no flag needed. If it reads `unresolved`, the cookie has
   expired: re-pull it (see [Failure modes](#failure-modes)).
5. **Eyeball the top 24.** Open the page and read the board top to bottom once. You are
   checking for the obvious: D/ST and K present, no position missing, nobody absurd at the
   top. If it looks wrong now it will look wrong at pick 8 and you will have no time.
6. **Open the window** and leave it open. Position it beside the ESPN draft room.
7. **Run one MCP query** in the Claude desktop app (`draft_status`) so the connector is
   approved before you need it. Approval mid-pick costs you the clock.

---

## During the draft

### Because manual entry is primary, the loop is:

1. Pick is called in the room.
2. Press `/`, type three or four letters of the name, press **Enter**.
3. The board updates. Next.

The Enter target is **named on screen** before you commit — `↵ marks Bijan Robinson`. Read it.
Marking the wrong player is the one mistake here that costs you a pick.

**Ctrl+Z** undoes the last mark without leaving the search box.

### The staleness indicator

| colour | age | meaning | action **if manual is primary** |
|---|---|---|---|
| green | < 10s | sync is keeping up | nothing — keep entering by hand anyway |
| amber | 10–30s | slow poll | nothing |
| red | > 30s | sync is not reporting | nothing |

**None of these change what you do**, because you are not relying on sync. The indicator is
there to tell you whether the sync *would* have been trustworthy — useful information for
next year, not an instruction tonight.

If the measurement later shows sync is fast and you switch to sync-primary, this table
becomes: green = trust the board; amber = glance at the draft room before each pick; red =
**do not trust availability**, enter by hand.

### Reading the board

- **Grab-now** is the headline: players unlikely to survive to your next pick. Empty at your
  final pick is correct (nothing to survive to). **At slot 8 you pick at the turn** — 8 and 9,
  16 and 17 — so you have back-to-back picks and then a long wait. Grab-now matters more to
  you than to a middle seat.
- **Three ranks stay three numbers.** Consensus, VORP, opportunity. When they disagree, that
  disagreement is the signal. It does not tell you who is right.
- **The board header says `SLEEPER-SOURCED`.** That is expected: League B's projections come
  from Sleeper stat lines scored through ESPN's weights. QB runs ~2% high and D/ST
  yards-allowed and kicker miss distance are unmodelled. It is not an error.

### What the analysis says to actually do

Two findings, both from cached data, both re-runnable (`audible anchoring`, `audible
rank-check`):

- **All seven opponents draft off ESPN's own board** (7/7, sign test p = 0.016). Nobody in
  this room is on a generic PPR board, so there is no whole-archetype mispricing to steal.
- **But our board and ESPN's diverge in rounds 3–10, and part of that divergence is
  reception-driven in the direction the scoring predicts** (WR |r| = 0.70, RB |r| = 0.62).

So the edge is **within position, not across it**:

- Among **WRs at a similar ESPN rank**, take the high-reception possession receiver over the
  low-volume deep threat. We pay 0.5 a catch; ESPN's ordering does not.
- Among **RBs**, fade the pass-catching back and prefer the pure rusher. We pay backs
  **nothing** per reception.

**Do not** act on the whole-position moves (QB and TE rising as blocks on our board). That is
VORP-versus-market structure, not receptions, and nothing has established which side is right.

---

## Failure modes

Each has one concrete first action.

### `/healthz` shows `data.origin: network` or the board will not build
**On the LOCAL cockpit** the disk cache is not being found. It lives in this repo at
`data/cache/` — there is no volume and no mount to check. Run `uv run audible refresh-data`,
then restart the launcher. If the network is also down and there is no cache, you are on the
paper board — go to rung 4.

Measured 2026-08-28, this is what a healthy laptop looks like:
`{"from_disk": 5, "from_network": 0, "origin": "disk"}`.

**On the cluster, `mixed` is normal and is not a fault** — the cache volume is an
`emptyDir` and is wiped every restart by design. Do not chase it mid-draft:
[the cluster has no disk guarantee](#the-cluster-has-no-disk-guarantee-and-cannot-have-one-here).

### ESPN cookies expired
Symptom: `/healthz` shows a board but `sync_status: failing`, or `my_slot_source: unresolved`,
or the CLI prints **"ESPN credentials expired, re-pull cookies"**.

fantasy.espn.com → DevTools → Application → Cookies. Copy `SWID` (**keep the curly braces**)
and `espn_s2` into `.env`, then restart the launcher. **This does not stop you drafting** —
manual entry needs no cookies at all, only the board, and the board is already built.

### Picks read 128 before the draft starts
The `playerId: -1` filter has broken. The board thinks the draft is over and will refuse to
show a clock. **Fall straight to manual entry** — mark each pick as it is called. The board's
availability is still correct; only the clock is wrong.

### Staleness goes red
Nothing to do if manual is primary. If you had switched to sync-primary: check the ESPN draft
room, and if its last pick does not match the cockpit, mark the missing picks by hand and keep
going. Do not restart mid-pick; a restart costs a board rebuild.

### The cockpit dies
1. Double-click `scripts/draft-day.cmd` again. **There is no `docker start audible-cockpit`**
   — that command, and the `audible-cache` volume it referenced, belong to a container path
   this launcher no longer uses.
2. **Synced picks are not lost** — they re-sync from ESPN on the next poll, and the session
   state file under `data/cache/` is reloaded on start. **Manual marks made in this instance
   are lost.** If you have been entering by hand all night, this is expensive: re-enter from
   the ESPN draft room's pick history.
3. If it will not start: read the server window — it is a foreground process and the error is
   in it, not in `docker logs`. Then drop to the cluster copy.

### The board looks obviously wrong
Trust the draft room, not the tool. Then ask which kind of wrong:
- **Wrong players available** → mark by hand.
- **Wrong roster slots / a position appearing that should not** → the league changed. Stop
  using the board's value numbers for the rest of the draft and fall back to consensus rank;
  run `verify-scoring` after.

### MCP is slow or unreachable
It is a between-picks tool, not an on-the-clock one. Ignore it and read the window. The UI is
the primary surface and never depends on MCP.

---

## Marking picks by hand

**This is the primary input tonight, not the fallback.**

- **In the UI:** `/` → type → **Enter** marks the top match. **Ctrl+Z** undoes. Or select a
  row and press `t`; `u` undoes.
- **In Claude:** `mark_taken` with the player id from any board tool; `undo_taken` reverses.

A manual mark is a **real pick** — numbered, attributed to whoever is on the clock, and it
advances the clock. That is what happened in the room, so that is what gets recorded.

This is **local state only** — nothing is ever written to ESPN. It survives a refresh and a
restart of the same cockpit (the session file under `data/cache/` is reloaded on start), but
**does not transfer between instances**: failing over from local to cluster loses your manual
marks. Everything else reconstructs.

---

## The endpoint is down and you are holding your phone

One page. Steps, not prose. **Work down and stop at the first one that gives you a board.**

Bookmark the two URLs in step 1 on the phone at T-24h. Looking them up at 19:01 is the
failure this page exists to prevent.

> **The draft does not need the internet, the tunnel, the cluster, or Flux.** It needs the
> laptop on the same wifi as the phone. Everything below is a way of getting back to that.

> ### ⚠️ READ THIS FIRST: the phone cannot reach the normal cockpit
>
> **`scripts\draft-day.cmd` binds `127.0.0.1`, on purpose** — "LOCALHOST ONLY … keeps the
> cockpit off the LAN entirely", added when the desktop became the primary surface. So the
> laptop's own browser works and **the phone is refused**, measured 2026-08-28:
>
> ```
> GET http://127.0.0.1:8080/healthz    -> 200 {"ok":true,...}
> GET http://192.168.1.21:8080/healthz -> WinError 10061, connection actively refused
> ```
>
> That is not an outage and rebooting will not change it. **To use the phone at all you must
> start the cockpit on `0.0.0.0` — go straight to step 4.** Steps 1 and 2 below apply only
> once you have done that.

### 1. Find out what is actually down — 10 seconds

Open both in Safari.

| tap | loads | does not load |
|---|---|---|
| `http://192.168.1.21:8080/healthz` | laptop cockpit is alive **and LAN-bound** → **step 2** | → **step 4** (not 3 — see the box above) |
| `https://mcp-audible.havenhomelab.org` | tunnel + cluster alive | ignore it — no rung below needs it |

`192.168.1.21` is the drafting machine (`iBUYPOWER`) on the LAN, confirmed 2026-08-28. If the
phone is on cellular it will not resolve — **turn wifi back on first.** Between that and the
loopback binding above, the two most likely "outages" are both not outages.

### 2. Cockpit is alive, so just use it — you are done

`http://192.168.1.21:8080` on the phone. Mark with the ✕ on each row, undo from the bottom
bar. Nothing else on this page applies.

### 3. Cockpit is dead → restart it — 30 seconds at the laptop

```cmd
scripts\draft-day.cmd
```

Re-running is always safe. **There is no container and no Docker on this path** — the
launcher runs `uv run audible serve` from this repo. (An earlier version of this step said it
"force-removes the old container first" and that "synced picks survive on the `audible-cache`
volume". Neither object exists any more; nothing here uses Docker.) Picks re-sync from ESPN on
the next poll. **Manual marks made in the dead instance do not survive** — re-enter them from
the ESPN draft room's pick history.

This gives you a LOOPBACK cockpit. If you need the phone, use step 4 instead.

### 4. The phone needs it → serve on the LAN — 1 minute

```bash
uv run audible serve --league espn_davis_drive --host 0.0.0.0 --port 8080
```

**`--host 0.0.0.0` is the whole point of this step**, and it is what step 3 does not do.
`serve` defaults to `127.0.0.1`, and so does `draft-day.cmd` deliberately — the laptop would
otherwise be serving a cockpit only the laptop can see. Verified 2026-08-28: with
`--host 0.0.0.0`, `GET http://192.168.1.21:8080/healthz` returns **200**; with the launcher's
default it is refused outright.

Then open `http://192.168.1.21:8080` on the phone exactly as in step 2.

This runs whatever is checked out, so `git log -1` is the version.

### 5. The board itself is wrong → roll back

Only if the cockpit *starts* but the board is obviously wrong.

**On the laptop, roll back SOURCE, not an image.** `scripts\draft-day.cmd` runs
`uv run audible serve` straight from this repo — it has no `AUDIBLE_IMAGE` variable and does
not use Docker at all. (An older version of this rung said to edit that variable. There is
nothing to edit; don't go looking for it at 19:40.)

```cmd
git checkout pre-draft-known-good
scripts\draft-day.cmd
```

Come back with `git checkout main`. The repo *is* the version on this machine, so `git log`
answers "what am I running" and a fix found at 19:45 is one restart away, not one CI build
away.

**Digests are for the CLUSTER** (rung 2). **Do not assume the table below says what is
running** — haven's Renovate automerges digest bumps for this image, so every push to
`audible@main` moves the cluster within minutes. Read the truth from
`kubernetes/apps/audible/deployment.yaml` on `haven@main`:

```bash
curl -s https://raw.githubusercontent.com/eyanric/haven/main/kubernetes/apps/audible/deployment.yaml   | grep 'image: ghcr'
```

These are rollback *targets* — they exist whether or not anything points at them:

| | digest | is |
|---|---|---|
| first with the seat pin | `sha256:3814af139b68db35e5be672988378386564533c77221402e8aca5c4b1b87e3ad` | `main` @ `1d5096b` — seat-8 pin, SEAT DRIFT guard, alarm fix |
| previous | `sha256:803a9fd04c6cb2f10381dc9c3e69986d9d7adb9b9bd3a447091f429ebd17969f` | `main` @ `d01332a` — every fix through PR #28 |
| **rollback** | `sha256:d3cdb2a101aaddfb88515956e93163d2f7bfa106273dd5da6e688d67339be570` | `main` @ `39a13f3` — known-good, **predates the replacement-level fix** |

Anything at or after `1d5096b` has the seat pin. Rolling back **past** it reintroduces
`my_slot: unresolved` on the cluster, and with it the silent loss of every timing term —
so prefer rung 1 over a deep cluster rollback.

Rolling the cluster back is a commit to `haven@main` (Flux reverts a `kubectl` edit within
ten minutes — see the kubectl section), and Renovate may bump it forward again afterwards.
**If the laptop still works, use rung 1 instead; it is faster and entirely in your hands.**

> **What the rollback costs you.** On `d3cdb2a1` the top D/ST ranks 33rd overall and D/ST and
> K are the eleven biggest "value" targets on the board. It is *known-good*, not *good*. Roll
> back only if the current image will not serve — not because the rankings look surprising.

### 6. Nothing runs → paper

The cheat sheet printed at T-24h. `uv run audible cheatsheet espn_davis_drive` if the laptop
still works at all. The top of the board barely moves in 24 hours.

---

### ✅ The cluster spare is usable again — verified 2026-08-28 04:12 UTC

**Both blockers are closed.** Rung 2 is back in the ladder.

The wrong-league blocker went first (haven #328/#329): the Deployment now carries
`--league espn_davis_drive`. The seat blocker went second (haven #330, audible #37): the
cluster was running `803a9fd0…`, an image that predated the seat pin, so `my_slot` read
`unresolved` even though sync was healthy. It now runs `3814af13…`.

Read back through the **public** endpoint, not the LAN shortcut:

```json
{"my_slot":8,"my_slot_source":"override","picks_until_mine":7,"my_next_pick":8,
 "rival_picks_before_my_next":7,"slack_picks":7,"my_picks_remaining":16,
 "unfilled_starting_slots":["QB","RB","RB","WR","WR","TE","FLEX","DEF","K"],
 "sync":{"age_seconds":0.9,"status":"live","last_success":"04:11:56","warning":null}}
```

Nine slots, `DEF`, no `SUPER_FLEX`, no `IDP_FLEX` — League B. Seat 8. Every timing term
non-null, so `recommend` carries survival percentages again instead of silently
degrading to best-available.

**Still confirm the league before trusting any cockpit.** The header must read
**DAVIS DRIVE ALUMNI FF LEAGUE · 8 TEAMS**, and `draft_status` must show nine starting
slots with `D/ST`. That habit cost nothing and caught this once already.

The old note here said the haven fix "cannot be pushed — branch protection requires a PR,
and haven's required checks fail instantly on an exhausted Actions budget." **That is no
longer true, and it was worth testing rather than believing:** haven #330 opened normally
and all eight required checks passed in under 15 seconds.

---

## Fallback ladder

Work down. Every rung still lets you draft.

| # | surface | how | loses |
|---|---|---|---|
| 1 | **local container** | `scripts/draft-day.cmd` → `localhost:8080` | — |
| 2 | **cluster spare** | `http://192.168.1.110` — verified League B, seat 8, 2026-08-28 | manual marks; board re-fetches on restart |
| 3 | **serve from source** | `uv run audible serve --league espn_davis_drive --host 0.0.0.0` | manual marks; needs a board build |
| 4 | **printed board** | `uv run audible cheatsheet espn_davis_drive` (do this at T-24h) | everything live |

> **League B has no CLI rung.** `audible live` polls Sleeper directly and is **Sleeper-only**.
> It will refuse to run for `espn_davis_drive` and tell you so. Do not reach for it at 8:40 —
> rung 3 is `serve`, and rung 4 is paper.

Rung 4 is why you print the cheat sheet the day before. If the laptop dies you still draft off
paper, and the top of the board barely moves in 24 hours.

---

## The manual-mark session file has no backstop

Found the hard way on 2026-08-28: `data/cache/draft-state-espn_davis_drive.json` was
discovered **corrupted to 225 bytes of spaces** part-way through a QA session, and had to be
restored from a copy taken beforehand. The cause was not established, so this is written as a
property of where the file lives rather than as a diagnosis.

What is certain, and each part is checked:

- It is the **only** record of manual marks. Synced picks reconstruct from ESPN; marks do not.
- It is **gitignored** (`.gitignore:16` -> `data/cache/`), so `git checkout` cannot bring it
  back. There is no copy of it anywhere in the repo.
- It sits inside **`C:\Users\eyanr\OneDrive\...`**, a cloud-synced directory. Sync, dedup and
  on-demand placeholder behaviour all operate on files under that root.

**Before the draft, take a copy outside OneDrive:**

```cmd
copy data\cache\draft-state-espn_davis_drive.json %TEMP%\draft-state-backup.json
```

If the cockpit comes up with picks missing or a broken session, that copy is the fastest route
back. Failing that, re-enter from the ESPN draft room's pick history -- the marks are
recoverable by hand, they are just tedious, and knowing that in advance is the point.

## Rung-by-rung verification — measured 2026-08-28, not remembered

Every rung was exercised against a live cockpit with an **isolated state_dir**; the real
draft session hash was unchanged at exit. Command on the left, literal result on the right.

| rung | what was run | what came back |
|---|---|---|
| 1 · local, loopback | `GET http://127.0.0.1:PORT/healthz` | **200** `{"ok":true,"players":3302,...,"origin":"disk"}` |
| 1 · local, from the phone's address | `GET http://192.168.1.21:PORT/healthz` | **refused** — `WinError 10061`. The launcher binds `127.0.0.1` |
| seat, no `--slot`, no network | `/api/state` → `clock.my_slot` | **8**, `my_slot_source: "override"` |
| 2 · cluster spare | `GET http://192.168.1.110/healthz` + `/api/state` | **200**, `draft_id 6012`, `players 3303`, `clock.my_slot 8` |
| 4 · LAN serve | `audible serve … --host 0.0.0.0` then `GET http://192.168.1.21:PORT/healthz` | **200** — this is the rung the phone needs |
| 5 · source rollback | `git checkout pre-draft-known-good` | tag exists; **no `AUDIBLE_IMAGE` to edit** — that variable is gone |
| 6 · paper | `uv run audible cheatsheet espn_davis_drive` | **rc=0**, 3302 players, CSV + HTML written to `cheatsheets/` |
| ladder note | `uv run audible live espn_davis_drive --slot 8` | **rc=1**, *"`live` polls Sleeper directly and is Sleeper-only…"* — the documented refusal is real |

**Three rungs were broken and are now fixed above:** the phone could not reach rung 1/2 at
all, rung 3 told you to restart a container that does not exist, and rung 5 told you to edit
a variable that does not exist. Each was true when written; each was falsified by a change
somewhere else.

### Standing rule: this file is re-verified after any change to the DEPLOY PATH

Not only after changes to this file. Every stale entry found on 2026-08-28 was introduced by
editing something else — the launcher dropping Docker, the cluster's league arg, the image
digest moving. The runbook was never wrong when written and nobody had to touch it for it to
become wrong.

So re-run the verification above whenever any of these changes, and correct what it
falsifies **in the same PR**:

- `scripts/draft-day.cmd` (or anything about how the cockpit is started locally)
- the Deployment in `eyanric/haven` — image digest, args, volumes
- the `serve` CLI surface: flags, defaults, or the host it binds
- `leagues/*.toml` seat, roster, or scoring structure

`uv run --extra nflverse python scripts/qa-desktop.py` covers the cockpit's own behaviour;
this table covers the rungs around it. Neither is optional after a deploy-path change.

## If latency gets measured

Run the temp draft with the measurement script already running:

```bash
uv run python scripts/espn_latency.py --league-id 102010124
# THEN start the draft in league 102010124 and let it run two or three rounds.
```

Latency cannot be reconstructed afterwards — the script has to be watching while picks happen.

| median lag | what changes |
|---|---|
| under ~15s | sync becomes primary; the staleness table above becomes an instruction, and you enter by hand only when it goes red |
| over ~30s, batchy, or out of order | nothing changes; manual entry stays primary |

---

## ~~BLOCKER~~ RESOLVED 2026-08-28: the cluster was serving the WRONG LEAGUE

> **Closed.** Kept for the diagnosis, not as a live instruction. The Deployment now carries
> `--league espn_davis_drive` and the endpoint answers League B with seat 8 — see
> [the cluster spare is usable again](#-the-cluster-spare-is-usable-again--verified-2026-08-28-0412-utc).
> Everything below describes the state on **2026-08-25**.

`http://192.168.1.110` — the container that `mcp-audible.havenhomelab.org` fronts — was
running **League A**, not League B. Measured against the live endpoint:

```
/healthz    players 7620              (League B is 3300)
            draft_id 1361543954792742912   (a SLEEPER draft id; League B's is "6012")
/api/state  league.key  "sleeper_boyfun"
            num_teams 10, superflex true, rounds 18
draft_status via MCP:
            unfilled ['QB','RB','RB','WR','WR','WR','TE','FLEX','SUPER_FLEX','K','IDP_FLEX']
            my_slot  None  (unresolved)
```

This is the failure the A3 note predicted and thought was closed: the image bakes
`--league sleeper_boyfun` as its default command, `scripts/draft-day.cmd` was fixed to
override it, **and the long-running cluster container was never restarted with that
override.** The launcher fix only ever applied to the local container on the Windows box.

So on the 30th, the cockpit Eric opens from `draft-day.cmd` is League B and correct, while
**anything asked through the public MCP endpoint answers off League A's superflex + IDP
board** — a 10-team Sleeper board, with Josh Allen priced as a superflex QB and linebackers
on the board, for an 8-team 1-QB ESPN draft. It will not error. It will answer confidently
and wrongly, which is worse.

It also does not know the seat (`my_slot: unresolved`), so survival and "picks until mine"
are dead on that instance even for League A.

**Fix before the draft** — this lives in the homelab deploy, not in this repo, so it is not
changed here. The container must be restarted with the league named explicitly, exactly as
the launcher does it:

```
audible serve --league espn_davis_drive --host 0.0.0.0 --port 8080
```

Then re-verify, and do not trust a 200:

```bash
curl -s http://192.168.1.110/api/state | grep -o '"key": "[^"]*"'   # must say espn_davis_drive
```

## The cluster fix lives in eyanric/haven, and kubectl WILL NOT hold

> **Both changes have LANDED** — the league arg in haven #328/#329, the image digest in
> haven #330. Nothing here is outstanding. **The `kubectl` warning below is still live and
> still matters**, because it applies to the next change as much as it did to these.

Established 2026-08-25 by reading the cluster, not by guessing:

```
kubectl -n audible get deploy audible
  image:            ghcr.io/eyanric/audible:latest
  imagePullPolicy:  Always
  args:             ["audible","serve","--league","sleeper_boyfun","--host","0.0.0.0","--port","8080"]
  labels:           kustomize.toolkit.fluxcd.io/name=apps

kubectl -n flux-system get kustomization apps
  path: ./kubernetes/apps   sourceRef: GitRepository/flux-system   prune: true   interval: 10m0s

kubectl -n flux-system get gitrepository flux-system
  url: https://github.com/eyanric/haven.git   branch: main
```

**Do not fix this with `kubectl patch` or `kubectl set args`.** Flux reconciles
`./kubernetes/apps` from `haven@main` every ten minutes with `prune: true`, so a live edit
comes back green, serves the right league for a few minutes, and is then silently reverted
-- possibly between two picks. That failure is worse than the current one, because the
current one is at least stable.

The change was two lines in **`eyanric/haven`, branch `main`, under `kubernetes/apps/`** (the
audible Deployment). As it now stands on `haven@main`:

```yaml
    args:
      - audible
      - serve
      - --league
      - espn_davis_drive        # was: sleeper_boyfun
      - --host
      - 0.0.0.0
      - --port
      - "8080"
    # main @ 1d5096b, the seat pin + drift guard + alarm fix, published 2026-08-28.
    # Re-resolve with the README snippet if anything merges after the freeze.
    image: ghcr.io/eyanric/audible@sha256:3814af139b68db35e5be672988378386564533c77221402e8aca5c4b1b87e3ad
```

That digest is recorded in README's *Draft-night rollback* section beside the old ones, so
there is still something to roll back to — the ladder is three rungs deep now: `3814af13…`
(current) → `803a9fd0…` (previous) → `d3cdb2a1…` (known-good, pre-sprint). Pin a digest
rather than leaving `latest`, which moves the moment anything merges.

The manifest now also sets `imagePullPolicy: IfNotPresent`, which is safe *because* the
image is pinned by digest: a digest is immutable, so "already present" and "what this
manifest asked for" are the same statement. `Always` would send the kubelet to GHCR on every
restart for no new information — putting a third party on the one restart path that must
work without the internet.

**That image has been run.** The `image` workflow's smoke test boots the artifact in a
container, requires it to answer HTTP (a 503 counts -- the app is up, the board is still
warming, which is exactly the "cannot start" failure the job exists to catch), checks the
`/healthz` contract keys and renders the index. It passed on run 32903747416, the build of
`main @ d01332a` that produced `sha256:803a9fd0...`. Board readiness is reported, not gated,
because that is a live-network question.

So "the new image is unexercised in a container" is NOT true, and it should not be the reason
to prefer the old pin. The same smoke test passed on run 33140727074, the build of
`main @ 1d5096b` that produced `sha256:3814af13...`.

**And it is no longer unexercised in the homelab either.** Flux picked up #330 on its own
within about 90 seconds of merge — no forced reconcile was needed — and the pod came back
Ready with `restartCount: 0`. To force it anyway, or to verify after any future change:

```bash
flux reconcile kustomization apps --with-source
kubectl -n audible rollout status deploy/audible

curl -s http://192.168.1.110/api/state | grep -o '"key": "[^"]*"'   # espn_davis_drive
curl -s http://192.168.1.110/healthz                                # players ~3300, not 7620
curl -s http://192.168.1.110/api/state | tr ',' '
' | grep my_slot # my_slot 8, not null
```

That last line is the one that would have caught this deploy's actual bug: the league was
already right while the seat was still `unresolved`, so checking the league alone reported
success on a cockpit that had no timing terms.

## The cluster has no disk guarantee, and cannot have one here

**Not draft-blocking. Do not try to fix this before Sunday.** It is written down because the
`data.origin: "disk"` check is stated elsewhere as a general property of the cockpit, and on
the cluster that claim is structurally false — so the check reads as a *failure* when it is
actually the design working.

The cluster's cache volume is an `emptyDir`:

```yaml
volumes:
  - name: cache
    emptyDir:
      sizeLimit: 1Gi
```

`emptyDir` lives and dies with the pod. Every restart hands the container an empty
`/app/data`, so the board rebuilds by going to the network. Measured on the fresh pod
immediately after the 2026-08-28 rollout, and again four minutes later:

| | local (`draft-day.cmd`) | cluster (`192.168.1.110`) |
|---|---|---|
| `from_disk` | 5 | 2 |
| `from_network` | 0 | **3** |
| `origin` | `disk` | `mixed` |

It does not converge. Those three sources were fetched over the network at boot and stay
network-origin for the life of the process, so the cluster reports `mixed` forever.

**Why this is not being "fixed" with a PVC.** The obvious repair — swap `emptyDir` for a
`ceph-block` PVC — buys the disk guarantee by putting the draft-night spare on Ceph's
availability, and the manifest rejects that deliberately: *"The draft tool must not be able
to die with Ceph."* That trade is wrong for this pod. A spare that re-fetches on boot has a
slow start; a spare that cannot schedule because storage is degraded is not a spare. The
`emptyDir` stays.

**What it actually costs on Sunday:** if the internet is down *and* the cluster pod restarts,
rung 2 comes back with no board. That is a two-failure scenario, and rung 1 — the local
cockpit, which genuinely is `origin: "disk"` — is unaffected by both. Rung 2 is the spare for
"the laptop died," not for "the internet died."

So, plainly: **the from-disk guarantee is a property of the LOCAL cockpit, not of the
cluster.** On `192.168.1.110`, `mixed` is healthy and expected. Do not chase it.

## Which seat am I? Slot 8 — derived when sync is up, pinned so it survives sync being down

Measured live 2026-08-25 -- `settings.draftSettings.pickOrder = [2, 3, 6, 4, 1, 5, 7, 8]`:

| slot | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| team id | 2 | 3 | 6 | 4 | 1 | 5 | 7 | 8 |
| abbrev | Ryan | Cnk | FAT | PM | **BTD** | JEFF | WCW | **BUTT** |

BUTT is team id 8 and **draft slot 8**. Slot 5 is BTD. `orderType` is `MANUAL`, so the
commissioner can reshuffle before Sunday.

**The seat is now ALSO pinned in config** — `draft_slot = 8` in
`leagues/espn_davis_drive.toml`, confirmed with the commissioner 2026-08-27 — which
reverses what this section used to say. The old reasoning was that deriving the seat from
`pickOrder` on every poll is strictly better than configuring it, because a `--slot` flag is
"a second place for the answer to be wrong." That is right about drift and **wrong about
outage**, which is the failure that actually happened: derivation only works while the sync
works, and an unresolved seat does not degrade loudly. It nulls `picks_until_mine`,
`my_next_pick`, `rival_picks_before_my_next` and `slack_picks` all at once, so `recommend`
drops its timing term and keeps answering with full confidence.

The drift objection was answered rather than ignored: if a live `pickOrder` ever resolves a
different seat, the service logs `SEAT DRIFT` at ERROR and says the pin is winning. So a
commissioner reshuffle is still caught — it is just caught in the log instead of silently
followed. **If you see `SEAT DRIFT`, believe the draft room, not the pin.**

The earlier note here — "`my_slot: null` on the cluster is not a bug in the seat resolver, it
is League A" — **was wrong.** The cluster was already serving League B when the seat still
read null on 2026-08-28; the real cause was the image predating the pin. Both are fixed, and
the cluster now answers `my_slot: 8, my_slot_source: "override"`, matching local exactly.

## League structure — re-verified live 2026-08-25

Every replacement baseline is derived from this, so it is checked rather than assumed.

**Source 1 — the raw ESPN API**, `settings.rosterSettings.lineupSlotCounts` on league 6012:

```
  0 QB    = 1        16 D/ST  = 1        20 BE = 7
  2 RB    = 2        17 K     = 1        21 IR = 3
  4 WR    = 2        23 FLEX  = 1
  6 TE    = 1
  total 19 slots - 3 IR = 16 DRAFTED ROUNDS      settings.size = 8
```

**Source 2 — `uv run audible verify-scoring espn_davis_drive`**, which re-reads the live
league through the adapter:

```
  roster structure is FAITHFUL (9 starting slots match)
  config scoring is FAITHFUL to the live league (48 position-scoped weights match)
  receptions confirmed LIVE at 0.5/rec for WR/TE (RB stays 0.0 by design, not drift)
```

**Starting lineup = QB, RB, RB, WR, WR, TE, FLEX, D/ST, K.** Nine starters, seven bench,
sixteen rounds, eight teams. This matches `leagues/espn_davis_drive.toml` exactly, so the
replacement constants stand and nothing needs recomputing.

`tests/test_config.py` pins it. A failure there means the live league moved: re-verify, then
recompute the baselines — the board will keep building either way, which is the danger.

---

## The public MCP endpoint: what is proven and what is not

Probed end to end on 2026-08-25, through Cloudflare anycast (104.21.81.77), not a LAN
shortcut:

| leg | result |
|---|---|
| DNS | resolves to Cloudflare, 4 addresses |
| edge → tunnel → origin | **works** — `401 {"error":"Unauthorized"}`, `Content-Type: application/json`, from mcp-auth-proxy |
| OAuth discovery | `/.well-known/oauth-protected-resource` **200**, `/.well-known/oauth-authorization-server` **200** (DCR at `/.idp/register`, PKCE S256) |
| all 9 MCP tools | **respond end to end** against the deployed container over the LAN leg |

**That 401 is the good outcome.** It is a JSON body from the origin, not a Cloudflare
challenge page — the tunnel is up and reaching the proxy. A Cloudflare artifact would be a
403 with HTML.

**The join is now PROVEN too — 2026-08-28.** Claude is connected to
`https://mcp-audible.havenhomelab.org`, the GitHub OAuth login is done, and `draft_status`
and `recommend` both answer *through the public URL*: 9 starting slots, `my_slot 8`, every
timing term non-null. That was the pass/fail test written here, and it passes. The whole
path — DNS → Cloudflare → tunnel → proxy → OAuth → FastMCP → board — is exercised end to
end, not leg by leg.

Re-run it if anything in the chain is touched: ask `draft_status` and check for 9 slots and
`my_slot 8`. **11 slots or `SUPER_FLEX` means the wrong-league blocker is back.**

Two soft spots in the proxy's OAuth, both in the homelab and neither changed here:

- The `401` carries **no `WWW-Authenticate` header**. RFC 9728 says a protected resource
  should point at its metadata there. Clients that only follow that header will not find
  the discovery document; clients that probe `/.well-known/...` directly are fine.
- `/.well-known/oauth-protected-resource/mcp` returns **401 instead of metadata**. Newer
  MCP clients try that path-specific variant *first*. The root variant works, so a client
  that falls back succeeds and one that does not, fails.

---

## Quick reference

```bash
docker logs -f audible-cockpit          # what is it doing
docker restart audible-cockpit          # keeps synced picks, loses manual marks
docker rm -f audible-cockpit            # stop entirely

curl localhost:8080/healthz             # board present? from disk? how stale?
curl localhost:8080/api/state | head    # full state
```

| thing | value |
|---|---|
| local | `http://localhost:8080` |
| cluster | `http://192.168.1.110` |
| MCP (LAN) | `<base>/mcp` — open, no auth, same as the UI |
| MCP (public) | `https://mcp-audible.havenhomelab.org` — GitHub OAuth at the proxy |
| league | `espn_davis_drive` — ESPN 6012, 8-team, 1-QB, half-PPR for WR/TE, **0.0 for RB** |
| roster | QB, 2×RB, 2×WR, TE, FLEX, D/ST, K = 9 starters, 7 bench, 16 rounds |
| me | team 8 → **draft slot 8** (the turn) |
| draft | snake, 90s pick timer |
