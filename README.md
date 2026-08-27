# audible

A personal, self-hosted fantasy-football decision engine for **two specific redraft
leagues** — one cockpit that values the same player differently in each, because each
league's exact scoring and structure is modeled as data and the value engine *derives*
everything from it.

- **League A — Sleeper** (`sleeper_boyfun`): 10-team, half-PPR, **SUPERFLEX**, deep
  tackle-heavy **IDP**, median-match. Scarce and floor-rewarding.
- **League B — ESPN** (`espn_davis_drive`): 8-team, 1-QB, no IDP. Shallow, ceiling-tolerant.
  *Target half-PPR; live league still standard until the commish flips it.*

## Principles

1. **Config-driven.** Scoring, roster slots, and slot eligibility live in `leagues/*.toml`,
   not in logic. Two configs, one engine.
2. **Deterministic math is deterministic.** All scoring / VORP / optimization is pure,
   tested Python. The LLM reasons *over* computed numbers — it never computes them.
3. **Adapter isolation.** Each source sits behind a clean interface; the unofficial ESPN
   API is quarantined to one file.
4. **ToS-clean & read-only.** Open Sleeper + nflverse; read-only ESPN. The tool advises; you execute.
5. **Opportunity over production.** Target volume/role inputs (snaps, routes, targets, air
   yards, red-zone) — they lead the box score.

## Setup

```bash
uv sync                      # core deps (pydantic, httpx)
uv sync --extra nflverse     # + nflreadpy for the opportunity/NGS layer
cp .env.example .env         # fill in ESPN cookies / API keys when needed
```

## CLI (Phase 0)

```bash
uv run audible configs                       # validate + summarise both leagues
uv run audible verify-scoring sleeper_boyfun # config scoring vs the live league
uv run audible vorp sleeper_boyfun --top 30  # per-position replacement + VORP (incl. IDP)
```

## Layout

```
leagues/                  league configs as data (TOML), validated by a Pydantic schema
src/audible/
  config/                 typed schema + loader
  models/                 internal domain models (PlayerProjection)
  scoring/                deterministic scoring engine (the core)
  adapters/               sleeper (live), nflverse (nflreadpy), espn (stub)
  value/                  replacement levels + VORP, derived from config
  cli.py
tests/                    offline tests over captured fixtures
```

See `CLAUDE.md` for the full project context and phasing.

## Data sources and attribution

- **Sleeper** — league, rosters, player catalog, projections and stats. Open API, read-only.
- **nflverse** (via `nflreadpy`) — opportunity components, weekly stats, snap counts,
  participation, depth charts, schedules, and the `ff_playerids` crosswalk.
- **ESPN** — league settings, draft results and preseason ranks for league 6012. Unofficial
  API, read-only, cookie auth.
- **Fantasy Football Calculator** — historical preseason ADP.
  *ADP data courtesy of [Fantasy Football Calculator](https://fantasyfootballcalculator.com).*
  Free for personal and commercial use, attribution requested. Fetched **once per season**
  and pinned to disk; nothing re-fetches at draft time.

Every source is cached to disk and the cockpit runs from that cache. `/healthz` reports
`data.origin: "disk"` when nothing touched the network, which is the state it must be in
before kickoff.

## Draft-night rollback

The one thing standing between a bad merge and a dead cockpit on draft night.

| | |
|---|---|
| known-good tag | **`pre-draft-known-good`** — `main` @ `6a03bb4`, tagged 2026-08-25 before the pre-draft sprint |
| pinned image digest | **`ghcr.io/eyanric/audible@sha256:d3cdb2a101aaddfb88515956e93163d2f7bfa106273dd5da6e688d67339be570`** |
| that digest is | `main` @ `39a13f3`, set in `scripts/draft-day.cmd` |
| **current image** | **`ghcr.io/eyanric/audible@sha256:803a9fd04c6cb2f10381dc9c3e69986d9d7adb9b9bd3a447091f429ebd17969f`** |
| that digest is | `main` @ `d01332a` — every fix through PR #28. `latest` and `sha-d01332a…` both resolve to it (checked 2026-08-25) |

The two rows are deliberate: **the old digest is not replaced, it is kept beside the new
one.** Rolling back means having somewhere to roll back to, and a digest overwritten in place
is a rollback target that no longer exists.

```bash
git checkout pre-draft-known-good     # source rollback
scripts\draft-day.cmd                 # at that tag it pins the KNOWN-GOOD digest (d3cdb2a…)
```

### Getting the current digest

CI publishes on every push to `main`: `latest` and `sha-<full-commit>`, which resolve to
the **same image**. So "rebuild off main" needs no local Docker — it has already
happened. To read the digest for whatever `main` is now:

```bash
SCOPE='repository:eyanric/audible:pull'
TOKEN=$(curl -s "https://ghcr.io/token?scope=$SCOPE&service=ghcr.io" | jq -r .token)
ACCEPT='application/vnd.oci.image.index.v1+json'
curl -sI -H "Authorization: Bearer $TOKEN" -H "Accept: $ACCEPT" \
  https://ghcr.io/v2/eyanric/audible/manifests/latest | grep -i docker-content-digest
```

Pin *that* digest, not `latest` — `latest` moves the moment anything merges, and on
draft night the one restart that matters is the one that quietly picks up a different
image.

**The pinned digest predates the pre-draft sprint.** It does not contain the
replacement-level fix, the scoring-correction guards, or the phone-drivable cockpit.
Running the pinned image is the *safe* option, not the *current* one — it is a known-good
board, and on that image D/ST and K sit far too high (the top D/ST ranks 33rd overall).

To ship the fixes instead, rebuild, re-pin, and **record the new digest here before
changing `draft-day.cmd`** — the digest above must stay readable as the thing to fall back
to. Never replace it in place; add the new one beside it.

No-Docker fallback, which needs neither the image nor the tag:

```bash
uv run audible serve --league espn_davis_drive
```
