# Draft day runbook — League B (ESPN)

**Friday 28 August, 8:30. ESPN league 6012. You are team 8, draft slot 8.**

One operator, one night, no second chance. Follow this while distracted.

**The one thing to remember:** every failure below ends somewhere you can still draft.
If you are lost, jump to [Fallback ladder](#fallback-ladder) and work down it.

> **Manual entry is the primary input until proven otherwise.**
> The sync latency against ESPN has never been measured, and the temp-league draft that was
> going to measure it **cannot work** — ESPN will not start a draft with unfilled slots.
> Until a number exists, treat the sync indicator as *informational* and enter picks by hand.
> Loosen this only if a measurement comes back under ~15s. See
> [Latency](#if-latency-gets-measured).

`audible` never writes to ESPN or Sleeper, so two copies can run at once without conflicting.
That is what *would* make failover a matter of opening a different URL — but read the
[Fallback ladder](#fallback-ladder) before assuming the other URL is the same league.

**League A (`sleeper_boyfun`) is a different runbook.** This one is League B only. Where they
differ is called out; the biggest is that **`audible live` does not work for League B.**

---

## T-24h — Thursday 27th

Run these the day before, not on the day. **This is also the freeze:** after these checks,
no merges, no rebuilds, no config edits.

**In order. Each one gates the next.**

```
[ ] 1  uv run audible verify-scoring espn_davis_drive      three lines must pass
[ ] 2  uv run audible refresh-data                         the only network-dependent step
[ ] 3  uv run audible cheatsheet espn_davis_drive          print it. paper is the floor.
[ ] 4  double-click scripts\verify-offline.cmd             must print PASS
[ ] 5  double-click scripts\draft-day.cmd                  start the pinned image
[ ] 6  curl localhost:8080/healthz                         ok:true, players>0, origin:disk
[ ] 7  open the page, double-click a row, Ctrl+Z           the input path, once, by hand
[ ] 8  FREEZE                                              no merges to main after this
```

Step 4 is the one people skip. **Do not freeze on a digest that prints FAIL.** Step 7 takes
ten seconds and is the only check that exercises the thing you will actually be doing 128
times on Friday.

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

**The image is already pinned.** `scripts/draft-day.cmd` points at an explicit digest —
`ghcr.io/eyanric/audible@sha256:d3cdb2a1…`, which is main @ `39a13f3`. `latest` can move
under you the night before; a digest cannot.

> **There is no Renovate config in this repo** — earlier versions of this runbook said to
> freeze it, and there is nothing here to freeze. The thing that actually moves is
> `ghcr.io/eyanric/audible:latest`, which the `image` workflow rebuilds on **every push to
> main**. The cluster copy pulls it (`imagePullPolicy: Always`); the launcher does not,
> because it is digest-pinned. **The code freeze is what protects this** — no merges to main
> after the 27th and nothing can move.

Note the launcher **overrides the image's baked command**. The image defaults to
`--league sleeper_boyfun`; draft night is League B, so `draft-day.cmd` passes
`audible serve --league espn_davis_drive` explicitly. One image serves either league and the
one you are drafting is visible in the launcher rather than buried in a layer.

**Re-prove the offline property on the pinned image — double-click
`scripts/verify-offline.cmd`.**

This is not the same check as the development one. It pulls the pinned digest, fills the cache
volume *using that same image*, then rebuilds both boards with `--network none` — the
container's network namespace removed entirely, so there is no interface to reach. It is the
check most likely to catch a packaging difference: a missing file, a wrong path, a volume that
is not where the code looks for it.

It prints **PASS** or **FAIL**. **Do not freeze on a digest that prints FAIL.**

**Start the pinned container and confirm it is running offline-capable:**

```bash
curl localhost:8080/healthz
```

You are looking for **three** fields:

```json
{"ok": true, "players": 3300, "data": {"origin": "disk", ...}}
```

- `ok: true` and a non-zero `players` — the board built.
- **`data.origin: "disk"`** — the board came from the cache, not the network. If this says
  `network` or `mixed`, `refresh-data` has not taken effect on the container; check that the
  `audible-cache` volume is mounted at `/app/data/cache`.

A 503 means the board is not built — read `message` on `/api/state`, it says what it is
waiting on.

---

## T-30m — Friday 8:00

1. **Start the local container** — double-click `scripts/draft-day.cmd`.
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
   approved before you need it — approval mid-pick costs you the clock. **Then read what it
   answered.** If `unfilled_starting_slots` contains `SUPER_FLEX` or `IDP_FLEX` you are
   talking to **League A** (the public `mcp-audible.havenhomelab.org` endpoint proxies the
   cluster pod, which serves League A). League B's slots are QB / RB / RB / WR / WR / TE /
   FLEX / DEF / K and nothing else. Point the connector at the **local** cockpit's `/mcp`,
   or just use the UI — it never depends on MCP.

---

## During the draft

### Because manual entry is primary, the loop is:

1. Pick is called in the room.
2. Press `/`, type three or four letters of the name, press **Enter**.
3. The board updates. Next.

The Enter target is **named on screen** before you commit — `↵ marks Bijan Robinson`. Read it.
Marking the wrong player is the one mistake here that costs you a pick.

**Ctrl+Z** undoes the last mark without leaving the search box.

**If your hand is already on the mouse: double-click the row.** A single click only selects —
deliberately, so a stray click while scrolling can never mark anyone. The ✕ at the right of
each row does the same thing and is visible without hovering.

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
The offline cache is not reaching the container. Check the `audible-cache` volume is mounted
at `/app/data/cache`. Then `uv run audible refresh-data` on the host and restart. If the
network is also down and there is no cache, you are on the paper board — go to rung 3.

### ESPN cookies expired
Symptom: `/healthz` shows a board but `sync_status: failing`, or `my_slot_source: unresolved`,
or the CLI prints **"ESPN credentials expired, re-pull cookies"**.

fantasy.espn.com → DevTools → Application → Cookies. Copy `SWID` (**keep the curly braces**)
and `espn_s2` into `.env`, then restart the container. **This does not stop you drafting** —
manual entry needs no cookies at all, only the board, and the board is already built.

### Picks read 128 before the draft starts
The `playerId: -1` filter has broken. The board thinks the draft is over and will refuse to
show a clock. **Fall straight to manual entry** — mark each pick as it is called. The board's
availability is still correct; only the clock is wrong.

### Staleness goes red
Nothing to do if manual is primary. If you had switched to sync-primary: check the ESPN draft
room, and if its last pick does not match the cockpit, mark the missing picks by hand and keep
going. Do not restart mid-pick; a restart costs a board rebuild.

### The container dies
1. `docker start audible-cockpit`, or double-click `scripts/draft-day.cmd` again.
2. **Nothing is lost — synced picks or manual marks.** Both live in the same session file on
   the `audible-cache` volume, written on every mark and restored on start. Do **not** start
   re-entering the night's picks from the ESPN draft room; check the board first. (An earlier
   version of this runbook said manual marks were lost here. They are not, and there is a
   test pinning it: `tests/test_service.py::test_state_survives_a_restart`.)
3. If it will not start: `docker logs audible-cockpit`, then go to rung 2 — `serve` from
   source. **Not** the cluster copy; it is League A.

### The cockpit renders but does not respond to clicks
1. **Check you are clicking the right thing.** A single click on a row only *selects*. To
   mark: **double-click the row**, or click the ✕ at the right of it, or `t` on the selected
   row, or type in the search box and press Enter. All four do the same thing.
2. If none of them respond, **double-click `scripts/diagnose-cockpit.cmd`**. It launches its
   own throwaway browser, drives the page, and writes `cockpit-report.txt` with console
   errors, failed requests and the result of every interaction. It exits non-zero when the
   page is genuinely inert, which is the answer you need before you start restarting things.
3. If it reports the page *is* interactive, the problem is the input path, not the app —
   fall back to the search box and Enter, which needs no mouse at all.

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
  row and press `t`; `u` undoes. Or **double-click the row** — the mouse path, and the one
  that does not require hitting a 26px button.
- **In Claude:** `mark_taken` with the player id from any board tool; `undo_taken` reverses.
  Note the MCP endpoint published at `mcp-audible.havenhomelab.org` answers for **League A**
  — see the fallback ladder. Use the UI.

A manual mark is a **real pick** — numbered, attributed to whoever is on the clock, and it
advances the clock. That is what happened in the room, so that is what gets recorded.

**It is written to disk the moment you make it** (`draft-state-espn_davis_drive.json`, in the
`audible-cache` volume at `/app/data/cache`) and restored on start. So it survives a browser
refresh, a `docker restart`, and even `docker rm -f` followed by the launcher again — as long
as the same volume is reused. Nothing is ever written to ESPN.

What it does **not** survive is a *different instance*: a second container with its own
volume, or serving from source, starts empty. Everything else reconstructs from sync.

---

## Fallback ladder

Work down. Every rung still lets you draft.

| # | surface | how | loses |
|---|---|---|---|
| 1 | **local container** | `scripts/draft-day.cmd` → `localhost:8080` | — |
| 2 | **serve from source** | `uv run audible serve --league espn_davis_drive` | manual marks; needs a board build |
| 3 | **printed board** | `uv run audible cheatsheet espn_davis_drive` (do this at T-24h) | everything live |

> ### The cluster copy at `192.168.1.110` is NOT a League B fallback
>
> **Read from the live cluster on 2026-08-20.** `Deployment/audible` in namespace `audible`
> runs `args: [audible, serve, --league, sleeper_boyfun, ...]`. It serves **League A**.
> Opening it mid-draft gives you a *correct board for the wrong league* — the kind of wrong
> that looks right, and the same failure A3 caught in the launcher and fixed only there.
>
> Two more things about that pod, both read from the manifest, both relevant on the night:
>
> - **`image: ghcr.io/eyanric/audible:latest`, `imagePullPolicy: Always`.** The spare is not
>   pinned and re-pulls on every restart. A3 pinned the launcher; the cluster still moves.
> - **Its cache volume is an `emptyDir`, not a PVC.** A pod restart wipes the board cache
>   *and* the draft state, so it rebuilds **from the network** — the offline property A3
>   proved does not hold there — and its readiness probe allows five minutes for that. It
>   also carries no `ESPN_S2`/`ESPN_SWID`, so sync and slot resolution could not work for
>   League B even if it were pointed at it.
>
> **That is why the ladder no longer has a cluster rung.** If you want one before the 28th it
> is additive rather than a change — `audible` performs no platform writes, so a second copy
> runs happily alongside League A's:
>
> - copy `Deployment/audible` to `audible-espn`, set `--league espn_davis_drive`, pin
>   `image:` to the digest the launcher already uses, mount a real PVC at `/app/data`, and
>   add the two ESPN cookies as secret env;
> - give it its own LoadBalancer IP and put **that** in this table.
>
> Do it **before the freeze** or not at all.

> **League B has no CLI rung either.** `audible live` polls Sleeper directly and is
> **Sleeper-only**. It refuses for `espn_davis_drive` in 0.3s and says so. Do not reach for
> it at 8:40 — rung 2 is `serve`, and rung 3 is paper.

Rung 3 is why you print the cheat sheet the day before. If the laptop dies you still draft off
paper, and the top of the board barely moves in 24 hours.

---

## If latency gets measured

**The temp-league route is dead, and following it wastes an evening.** ESPN will not start a
draft with unfilled slots: every seat must be filled before the listed start time or the
draft is pushed back in five-minute intervals, indefinitely. Solo league `102010124` was
never going to produce a number, and read read-only it shows `drafted: false`,
`inProgress: false`, **0 real picks**.

The only route that can work is a **real, full draft you can join** — a public ESPN league
drafting in the next day or two — with the script running *first*:

```bash
uv run python scripts/espn_latency.py --league-id <that league's id>
# THEN let two or three rounds happen.
```

Latency cannot be reconstructed afterwards; the script has to be watching while picks happen.
**This is optional.** Manual entry is primary and this runbook assumes it, so an unmeasured
latency costs nothing on the night.

| median lag | what changes |
|---|---|
| under ~15s | sync becomes primary; the staleness table above becomes an instruction, and you enter by hand only when it goes red |
| over ~30s, batchy, or out of order | nothing changes; manual entry stays primary |

---

## Quick reference

```bash
docker logs -f audible-cockpit          # what is it doing
docker restart audible-cockpit          # keeps EVERYTHING: synced picks and manual marks
docker rm -f audible-cockpit            # stop entirely; state survives on the volume

curl localhost:8080/healthz             # board present? from disk? how stale?
curl localhost:8080/api/state | head    # full state
```

| thing | value |
|---|---|
| local | `http://localhost:8080` |
| cluster | `http://192.168.1.110` — **League A. Not a League B fallback.** |
| MCP (LAN) | `<base>/mcp` — open, no auth, same as the UI. Local base = League B. |
| MCP (public) | `https://mcp-audible.havenhomelab.org` — GitHub OAuth, and it proxies the **cluster** pod, so it answers for **League A** |
| league | `espn_davis_drive` — ESPN 6012, 8-team, 1-QB, half-PPR for WR/TE, **0.0 for RB** |
| roster | QB, 2×RB, 2×WR, TE, FLEX, D/ST, K = 9 starters, 7 bench, 16 rounds |
| me | team 8 → **draft slot 8** (the turn) |
| draft | snake, 90s pick timer |
