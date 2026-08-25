# Draft day runbook — League B (ESPN)

**Friday 28 August, 8:30. ESPN league 6012. You are team 8, draft slot 8.**

One operator, one night, no second chance. Follow this while distracted.

**The one thing to remember:** every failure below ends somewhere you can still draft.
If you are lost, jump to [Fallback ladder](#fallback-ladder) and work down it.

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

## T-24h — Thursday 27th

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

**The image is already pinned.** `scripts/draft-day.cmd` points at an explicit digest —
`ghcr.io/eyanric/audible@sha256:d3cdb2a1…`, which is main @ `39a13f3`. `latest` can move
under you the night before; a digest cannot. **Freeze Renovate for the week** so nothing
auto-merges a base-image bump.

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
The offline cache is not reaching the container. Check the `audible-cache` volume is mounted
at `/app/data/cache`. Then `uv run audible refresh-data` on the host and restart. If the
network is also down and there is no cache, you are on the paper board — go to rung 4.

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
2. **Synced picks are not lost** — state persists to the `audible-cache` volume and restores
   on start. **Manual marks made in this instance are lost.** If you have been entering by
   hand all night, this is expensive: re-enter from the ESPN draft room's pick history.
3. If it will not start: `docker logs audible-cockpit`, then drop to the cluster copy.

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
restart of the same container, but **does not transfer between instances**: failing over from
local to cluster loses your manual marks. Everything else reconstructs.

---

## Fallback ladder

Work down. Every rung still lets you draft.

| # | surface | how | loses |
|---|---|---|---|
| 1 | **local container** | `scripts/draft-day.cmd` → `localhost:8080` | — |
| 2 | **cluster spare** | open `http://192.168.1.110` | manual marks |
| 3 | **serve from source** | `uv run audible serve --league espn_davis_drive` | manual marks; needs a board build |
| 4 | **printed board** | `uv run audible cheatsheet espn_davis_drive` (do this at T-24h) | everything live |

> **League B has no CLI rung.** `audible live` polls Sleeper directly and is **Sleeper-only**.
> It will refuse to run for `espn_davis_drive` and tell you so. Do not reach for it at 8:40 —
> rung 3 is `serve`, and rung 4 is paper.

Rung 4 is why you print the cheat sheet the day before. If the laptop dies you still draft off
paper, and the top of the board barely moves in 24 hours.

---

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

## BLOCKER: the cluster is serving the WRONG LEAGUE (measured 2026-08-25)

`http://192.168.1.110` — the container that `mcp-audible.havenhomelab.org` fronts — is
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

The change is two lines in **`eyanric/haven`, branch `main`, under `kubernetes/apps/`** (the
audible Deployment):

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
    image: ghcr.io/eyanric/audible@sha256:<digest>   # was: :latest
```

Resolve `<digest>` with the snippet in README's *Draft-night rollback* section. Pin it
rather than leaving `latest`: `imagePullPolicy: Always` means a pod that restarts for any
reason on draft night pulls whatever `latest` points at by then.

Then force the reconcile instead of waiting out the interval, and verify:

```bash
flux reconcile kustomization apps --with-source
kubectl -n audible rollout status deploy/audible

curl -s http://192.168.1.110/api/state | grep -o '"key": "[^"]*"'   # espn_davis_drive
curl -s http://192.168.1.110/healthz                                # players ~3300, not 7620
```

## Which seat am I? Slot 8, and it is derived, not configured

Measured live 2026-08-25 -- `settings.draftSettings.pickOrder = [2, 3, 6, 4, 1, 5, 7, 8]`:

| slot | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| team id | 2 | 3 | 6 | 4 | 1 | 5 | 7 | 8 |
| abbrev | Ryan | Cnk | FAT | PM | **BTD** | JEFF | WCW | **BUTT** |

BUTT is team id 8 and **draft slot 8**. Slot 5 is BTD. `orderType` is `MANUAL`, so the
commissioner can reshuffle before Sunday -- and the sync re-derives the seat on every poll
rather than caching it, so a reshuffle is followed automatically. **Nothing needs to be
configured, and nothing should be: a `--slot` flag would just be a second place for the
answer to be wrong.**

`my_slot: null` on the cluster is not a bug in the seat resolver. It is League A: Sleeper's
`draft_order` is null until the draft opens, which is documented Sleeper behaviour. On
League B, locally, the same code answers `my_slot: 8, my_slot_source: "pick_order"`.

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

**Not proven, and it needs a human:** completing a tool call *through* the public URL
requires the GitHub OAuth browser login. The two legs are each proven; the join is not.
**Do this before the 30th:** connect Claude to `https://mcp-audible.havenhomelab.org`, log
in, and ask it `draft_status`. If it answers with 9 starting slots and `my_slot 8`, the
whole path is good. If it answers with 11 slots and `SUPER_FLEX`, the blocker above is
still live.

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
