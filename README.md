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

## Draft-night rollback

The one thing standing between a bad merge and a dead cockpit on draft night.

| | |
|---|---|
| known-good tag | **`pre-draft-known-good`** — `main` @ `6a03bb4`, tagged 2026-08-25 before the pre-draft sprint |
| pinned image digest | **`ghcr.io/eyanric/audible@sha256:d3cdb2a101aaddfb88515956e93163d2f7bfa106273dd5da6e688d67339be570`** |
| that digest is | `main` @ `39a13f3`, set in `scripts/draft-day.cmd` |

```bash
git checkout pre-draft-known-good     # source rollback
scripts\draft-day.cmd                 # already pins the digest above at this tag
```

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
