# Backtest leakage audit

Every input the opportunity model consumes, classified **as-of-draft-day** (legitimately
knowable when the pick is made) or **as-of-season-end** (only knowable afterwards).

Verified 2026-08-26 against the live frames, not against the docstrings.

The headline: **the production 2026 board is clean, and the same code used for a backtest
fold is not.** Two inputs are clean today only because 2026 data does not exist past today.
Point them at a completed season and they silently answer with what happened.

## The board

| input | what the model takes | timing | verdict |
|---|---|---|---|
| `opportunity_frame([Y-1])` | the 11 `*_exp` components, summed over the season | season-end Y-1 | **as-of-draft-day for Y** |
| `trajectory_factors(Y-1)` | targets+carries per week; season mean vs last-N mean | season-end Y-1 (incl. POST) | **as-of-draft-day for Y** |
| `team_vacated_shares(Y-1, Y)` | target/carry share of players who left | season-end Y-1 | **as-of-draft-day for Y** |
| `load_draft_capital(Y)` | round and pick for rookies | NFL draft, April of Y | **as-of-draft-day** |
| `raw_player_lines(config, Y)` | Sleeper preseason stat lines | preseason Y | **as-of-draft-day**, but see *Not available historically* |
| `schedules_frame([Y])` | bye weeks | published spring Y | **as-of-draft-day** |
| `rosters_frame([Y])` → `current_team_by_gsis` | gsis → team | **week 1 of Y** | ⚠️ **near-miss** |
| `id_map_frame()` (ff_playerids) | sleeper/espn/gsis/pfr crosswalk | fetched now, carries no season | ⚠️ **present-tense** |

## Lane 1 usage context

| input | what it takes | timing | verdict |
|---|---|---|---|
| `player_stats_frame([Y-1])` | mean weekly `target_share`, `air_yards_share` | season-end Y-1 | **as-of-draft-day for Y** |
| `snap_counts_frame([Y-1])` | mean `offense_pct` | season-end Y-1 | **as-of-draft-day for Y** |
| `route_participation_frame(Y-1)` | charted-route plays on field / team charted-route plays | season-end Y-1 | **as-of-draft-day for Y** |
| `depth_chart_slots_frame(Y)` | `pos_rank` at the **latest `dt`** | **latest `dt` in the season** | ❌ **LEAKS on any past fold** |

## The two that bite

### `depth_chart_slots_frame` — outright leakage on a past fold

`load_depth_charts([Y])` returns every chart snapshot of the season, and the aggregation
keeps the most recent. Measured:

| season | rows | `dt` span | latest-`dt` resolves to |
|---|---|---|---|
| 2026 (current) | 472,351 | 2026-03-22 → **2026-08-26** | today — correct |
| 2025 (complete) | 554,215 | 2025-08-03 → **2026-03-14** | **week 18 / post-season** |

For the live board this is exactly right: the newest chart *is* the draft-day chart, because
nothing later exists yet. For a 2025 fold it answers with who finished the season as WR1 —
which is a fact about the outcome the backtest is trying to predict.

**Required for Task 1:** an `as_of` cutoff, defaulting to the draft date of fold year Y, so
the aggregation keeps the newest snapshot *at or before* that date.

### `rosters_frame([Y])` — a near-miss, not a leak, but not free either

nflverse rosters are weekly. The 2026 frame carries **week 1 only**; 2025 carries weeks
1–18. `current_team_by_gsis` filters non-null `gsis_id` and takes `.unique(keep=first)`,
so on a completed season the team it reports is whichever week sorted first — not
necessarily the August team.

Even at week 1 this is ~2 weeks *after* an August draft: final cuts, late signings and
week-1 IR have already happened. It is a small forward-looking edge rather than an outcome
leak, but a backtest that claims as-of-draft-day inputs should clamp to `week == 1` and say
so, which is what the 2026 frame happens to give for free.

## Present-tense, and unavoidable

`ff_playerids` carries no season. It reflects today's identities — a player who has since
changed teams, retired or been re-mapped resolves with today's row. This affects *joins*,
not values, so it cannot leak an outcome into a projection; it can only cause a fold to
match or miss a player. Recorded because "the crosswalk is as-of-now" is the kind of fact
that gets re-derived at 2am otherwise.

## Not available historically

`raw_player_lines` needs **Sleeper preseason projections for season Y**, and only 2026 is
held. There is no cached 2021–2025 projection snapshot and no free way to recover one after
the fact.

This is what rules out replaying arms B and C on 2026 inputs against older seasons: the
projection would carry knowledge no August drafter had. The harness therefore builds its
arms from **prior-season observed usage** (`ff_opportunity` Y-1), which *is* recoverable
as-of-draft-day for every fold, and takes the market arm from ESPN's own preseason ranks:

| arm | source | as-of |
|---|---|---|
| **A** — ESPN raw | `espn_ranks_6012_{Y}.standard` — the board this room actually drafted from | preseason Y |
| **B** — ESPN re-scored | `espn_ranks_6012_{Y}.ppr` — ESPN's own order for a reception-paying league | preseason Y |
| **C** — full model | opportunity xFP from `ff_opportunity` Y-1, scored through DDAFFL half-PPR | season-end Y-1 |
| **labels** | half-PPR points from `player_stats` Y, via the scoring engine | season-end Y |

Folds are **2023, 2024, 2025** — the seasons with both an `espn_ranks` snapshot and a
completed set of actuals.

`espn_ranks` ships `standard` and `ppr` for the same player, which is what makes A and B
separable without inventing a projection: the league scored standard through 2025, so A is
the order the room used and B is the same source re-expressed for scoring that pays
receptions. Half-PPR sits between them, so B is the nearer of the two to DDAFFL and A is
the anchor the seven opponents actually held.
