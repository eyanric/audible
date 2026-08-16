# audible — project context for Claude Code

Personal, self-hosted fantasy-football decision engine for **two specific redraft leagues**.
No money, no other users — that freedom is the point: hardcode for *my* two leagues and
optimize ruthlessly. The product is one cockpit over both, where the same player is valued
differently in each because each league's exact scoring/structure is modeled as data.

## Load-bearing principles (honor everywhere)

1. **Config-driven, league-aware.** Scoring, roster slots, slot eligibility, team count
   live in `leagues/*.toml`, validated by `config/schema.py`. The value engine *derives*
   replacement baselines and scarcity from the config. No league-specific branches in logic.
2. **Deterministic math is deterministic.** Scoring, VORP/replacement, projection blending,
   and (later) lineup optimization are pure, tested, reproducible Python. **The LLM never
   does arithmetic** — it reasons over computed numbers and returns judgment.
3. **Adapter isolation.** Each source sits behind a clean interface in `adapters/`. The ESPN
   adapter rides an unofficial API — keep it a one-file fix when it breaks.
4. **ToS-clean, read-only.** Sleeper (open), nflverse (open), ESPN (read-only, cookie auth).
   No writes to any platform. Secrets via `.env`, never committed.
5. **Opportunity over production.** Target volume/role inputs (snaps, routes, targets, air
   yards, red-zone) — they lead the box score and are stickier than past fantasy points.
6. **Verify before relying.** Confirm exact endpoints/fields/signatures against live
   docs/source before building on them.

## The two leagues

- **League A — Sleeper `sleeper_boyfun`** (id 1361543954771738624): 10-team, half-PPR,
  **SUPERFLEX**, deep **IDP** (DL/LB/DB/IDP_FLEX), median-match (`league_average_match`),
  6/10 playoffs at Wk15, FAAB $100. Full redraft (keeper fields are vestigial copy
  artifacts). Quirks encoded: `pass_int = -2`, big-play bonuses ON (`rec_40p`, `rush_40p`,
  `rec_30_39`), first-down bonuses OFF, distance kicker (`fgm_yds = 0.1`), tackle-heavy IDP
  (`idp_tkl_solo = 2`, `idp_sack = 6`).
- **League B — ESPN `espn_davis_drive`** (id 6012): 8-team, 1-QB, no IDP (team D/ST only).
  **Target half-PPR**, but the live league is still standard (0 PPR) until the commish
  flips it — the ESPN adapter must verify live `scoring_format` (statId 53 = REC) against
  `expected_reception_points` and flag mismatch loudly.

## Verified data-source facts (2026-06)

- **Sleeper.** League/roster/players on `api.sleeper.app/v1`; **projections/stats on
  `api.sleeper.com`** (undocumented, source = Rotowire). Projections ship only
  std/half/full-PPR point totals **and granular stats including IDP** (`idp_tkl_solo/ast`,
  `idp_sack`, `idp_int`, `idp_ff`, `idp_fum_rec`) — so we recompute every player's points
  from the raw line via the scoring engine; never trust the precomputed `pts_*`. Players
  catalog is ~15 MB / 12k players — cache once/day. IDP eligibility keys off
  `fantasy_positions` (DL/LB/DB), which can be hybrid (DE → `["DL","LB"]`); the granular
  `position` field maps to the VORP primary bucket so two-way players (WR/DB) bucket to offense.
- **nflverse.** `nfl_data_py` is **archived** — use **`nflreadpy`** (returns polars; convert
  at the adapter boundary). Id spine: `load_ff_playerids()` carries `sleeper_id`/`espn_id`/
  `gsis_id`. NGS via `load_nextgen_stats(stat_type=...)`; snaps via `load_snap_counts`.
  Route participation is a known gap (FTN, delayed/post-season only).
- **ESPN.** `cwendt94/espn-api` (0.46.x). `League(league_id, year, espn_s2, swid)`; swid keeps
  braces. Projected vs actual on `BoxPlayer.projected_points` / `.points`.
- **FastMCP.** Use standalone `fastmcp` v3 (not the SDK's FastMCP 1.0). Streamable HTTP
  (`transport="http"`), `app = mcp.http_app()` behind the reverse proxy, `StaticTokenVerifier`.
- **Optimizer.** Use **OR-Tools CP-SAT** (in-process, deterministic with `num_workers=1` +
  `random_seed`), not PuLP (lost its bundled CBC binary).

## Stack

Python 3.12+ / uv · Pydantic (config + models) · httpx (Sleeper) · nflreadpy (extra) ·
FastAPI + uvicorn (cockpit) · OR-Tools CP-SAT (deferred) · FastMCP (Phase 3) ·
pytest / ruff / pyright. **No Anthropic SDK — `audible` never calls a model.**

## Layout

`leagues/*.toml` (data) · `src/audible/{config,models,scoring,adapters,value,draft,server,cli}` ·
`tests/` (offline, fixture-backed). `optimize/` arrives with its phase.

## Commands

```bash
uv sync [--extra nflverse]
uv run audible configs
uv run audible verify-scoring sleeper_boyfun
uv run audible vorp sleeper_boyfun --top 30
uv run pytest          # offline
uv run ruff check .
uv run pyright
```

## Phasing (don't run ahead)

- **Phase 0 (DONE when shown & accepted):** scaffold, both configs validated, Sleeper +
  nflverse adapters, ESPN stub, **Sleeper VORP baselines incl. IDP, end-to-end.**
- **Phase 1:** per-league value engine, projection blend (ESPN+Sleeper native), CP-SAT
  lineup optimizer, **draft assistant** (highest preseason value).
- **Phase 2:** nflverse/NGS ingestion + breakout detection; `start_sit`, `waiver_targets`.
- **Phase 3 — MCP surface, not a reasoning layer.** `audible` makes **no model calls** and holds
  **no API key**; there will not be one. Instead it *exposes* itself over MCP (FastMCP mounted
  into the cockpit's FastAPI app, streamable HTTP, bearer token from `MCP_AUTH_TOKEN`) so Claude
  on the Max subscription can query it conversationally. The recommendation engine stays fully
  deterministic — Claude reads tool output and reasons about it; it never computes a ranking.
  That keeps the engine testable, replayable against a past draft, and identical whether you
  read it in the UI or ask about it in chat. Plus Docker/homelab deploy.
- **Phase 4:** full IDP modeling, `trade_evaluator`, proactive alerts.

## Conventions

- Named exports/clear public APIs; comments explain *why*. No backwards-compat shims.
- Deterministic core stays pure and tested; never let the LLM compute numbers.
- Tests run offline against `tests/fixtures/` — refresh fixtures from live when the API shifts.
