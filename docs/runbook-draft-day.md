# Draft day runbook

One operator, one night, no second chance. Follow this while distracted.

**The one thing to remember:** every failure below ends somewhere you can still draft.
If you are lost, jump to [Fallback ladder](#fallback-ladder) and work down it.

`audible` never writes to Sleeper or ESPN. Two copies can run at once without conflicting,
which is why failover is just opening a different URL.

---

## T-24h

Run these the day before, not on the day.

```bash
# 1. Did the league change under us? It did once already, in July.
uv run audible verify-scoring sleeper_boyfun
#    Expect BOTH lines to say FAITHFUL. Roster drift silently corrupts every
#    replacement baseline, so a mismatch here invalidates the whole board.

# 2. Refresh the consensus archive.
uv run audible snapshot

# 3. Confirm the board still builds and looks sane.
uv run audible draft sleeper_boyfun --top 40
```

**Pin the image digest.** Get it from the `image` workflow summary on the merge commit you
want, then edit `scripts/draft-day.cmd`:

```
set "AUDIBLE_IMAGE=ghcr.io/eyanric/audible@sha256:<digest>"
```

`latest` can move under you the night before. A digest cannot. **Freeze Renovate for the
week** so nothing auto-merges a base-image bump.

**Start both copies and check each:**

| copy | check |
|---|---|
| local | double-click `scripts/draft-day.cmd`, then `curl localhost:8080/healthz` |
| cluster | `curl http://192.168.1.110/healthz` |

Both should return `{"ok":true, ...}` with a non-zero `players` count. A 503 means the board
is not built — read `message` on `/api/state`, it says what it is waiting on.

---

## T-30m

1. **Start the local container** — double-click `scripts/draft-day.cmd`. It pulls, starts,
   waits for the board, and opens the browser.
2. **Confirm the draft was found.** On `/healthz`, `draft_id` should be non-null. The server
   rediscovers it at every startup, so if the commissioner recreated the draft while
   scheduling it, that is already handled.
3. **Confirm your slot resolved.** On the page, the top bar shows your pick countdown. In
   `/api/state`, `clock.my_slot_source` should be `draft_order` once the draft opens.
   Until then it reads `unresolved` — that is correct, not a bug. `slot_to_roster_id` is a
   placeholder before the draft starts and must never be trusted; pass `--slot N` only if you
   need to force it.
4. **Open the window** and leave it open. Position it beside the Sleeper draft room.
5. **Run one MCP query** in the Claude desktop app (`draft_status`) so the connector is
   approved before you need it. Approval mid-pick costs you the clock.

---

## During the draft

### The staleness indicator is the only thing you must watch

| colour | age | meaning | action |
|---|---|---|---|
| green | < 10s | live | none |
| amber | 10–30s | slow poll | glance at Sleeper to confirm the last pick matches |
| red | > 30s | **do not trust availability** | check the draft room before every pick; see below |

Measured normal is **0.3–0.5s**. Amber is unusual. Red means the board may be showing a player
who is already gone, which is the worst failure this tool has.

### Reading the board

- **Grab-now** is the headline: players unlikely to survive to your next pick. Empty at your
  final pick is correct (nothing to survive to).
- **Three ranks stay three numbers.** Consensus, VORP, opportunity. When they disagree, that
  disagreement is the signal — a `DEV` marker means the opportunity model departs sharply from
  consensus. It does not tell you who is right.
- **A superflex QB run is the loudest thing in the right column** for a reason: two QB-capable
  slots across ten teams means a run empties the position fast.

---

## Failure modes

Each has one concrete first action.

### Staleness goes red
1. Check the Sleeper draft room. Does its last pick match the cockpit's?
2. If yes, the poll is slow but the board is right — keep going, watch it.
3. If no, **mark the missing picks by hand** (see below) and keep drafting. Do not restart
   mid-pick; a restart costs a board rebuild.
4. After your pick, if it stays red: `docker restart audible-cockpit`.

### The container dies
1. `docker start audible-cockpit`, or double-click `scripts/draft-day.cmd` again.
2. **Picks are not lost** — state persists to the `audible-cache` volume every poll and
   restores on start. What *is* lost is manual mark-taken overrides.
3. If it will not start: `docker logs audible-cockpit`, then drop to the cluster copy.

### Sleeper returns 5xx
Nothing to do. The poller backs off with jitter and holds last-known state; staleness rises
and recovers on its own. Verified: the page held a full board through a 33-second outage and
recovered unattended.

### The board looks obviously wrong
Trust the draft room, not the tool. Then ask which kind of wrong:
- **Wrong players available** → sync problem, mark by hand.
- **Wrong roster slots / DEF appearing** → the league changed. Stop using the board's value
  numbers for the rest of the draft and fall back to consensus rank; run `verify-scoring`
  after. Replacement baselines derive from roster structure, so a roster mismatch makes every
  VORP number wrong.

### MCP is slow or unreachable
It is a between-picks tool, not an on-the-clock one. Measured 7–18 ms locally, but if the
connector misbehaves, **ignore it and read the window.** The UI is the primary surface and
never depends on MCP.

### The cluster copy is down
Irrelevant during the draft — it is the spare. Keep using local.

---

## Marking picks by hand

The universal fallback. Works when any sync fails, and is the only path for a league with no
sync at all.

- **In the UI:** select the row and press `t`. `u` undoes.
- **In Claude:** `mark_taken` with the player id from any board tool; `undo_taken` reverses.

This is **local state only** — nothing is ever written to Sleeper. It survives a refresh and a
restart of the same container, but **does not transfer between instances**: failing over from
local to cluster loses your manual overrides. Everything else reconstructs from Sleeper.

---

## Fallback ladder

Work down. Every rung still lets you draft.

| # | surface | how | loses |
|---|---|---|---|
| 1 | **local container** | `scripts/draft-day.cmd` → `localhost:8080` | — |
| 2 | **cluster spare** | open `http://192.168.1.110` | manual overrides |
| 3 | **serve from source** | `uv run audible serve --league sleeper_boyfun` | manual overrides; needs a board build |
| 4 | **CLI** | `uv run audible live sleeper_boyfun --slot N --watch 5` | the UI; text only |
| 5 | **printed board** | `uv run audible cheatsheet sleeper_boyfun` (do this at T-24h) | everything live |

Rung 5 is why you print the cheat sheet the day before. If the laptop dies you still draft off
paper, and the top of the board barely moves in 24 hours.

---

## Quick reference

```bash
docker logs -f audible-cockpit          # what is it doing
docker restart audible-cockpit          # keeps picks, loses manual overrides
docker rm -f audible-cockpit            # stop entirely

curl localhost:8080/healthz             # board present? how stale?
curl localhost:8080/api/state | head    # full state
```

| thing | value |
|---|---|
| local | `http://localhost:8080` |
| cluster | `http://192.168.1.110` |
| MCP | `<base>/mcp`, bearer `MCP_AUTH_TOKEN` |
| league | `sleeper_boyfun` (10-team, superflex, 1 IDP_FLEX, 18 rounds) |
| draft | snake, 60s pick timer |
