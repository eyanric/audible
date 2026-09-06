# `sim/` — defect reproduction gates

**These gates are RED on purpose. Red is the deliverable.**

Four defects were found by a human noticing a bad recommendation mid-draft, across three
drafts. `docs/STATE.md` records all four as measured and deliberately unfixed. This package
reproduces them offline, deterministically, from hand-built board and roster states — so
that the fixes have something to turn green, and so a fifth defect of the same shape cannot
hide.

A harness that cannot detect four defects you already know about cannot detect one you do
not.

## Running them

```
uv run pytest sim -m slow
```

They are excluded from `uv run pytest` two independent ways: `testpaths = ["tests"]` does
not reach this directory, and `addopts` carries `-m "not slow"`. The default run must stay
fast — it is what gates draft day. Adding a gate cannot forget the marker: `sim/conftest.py`
applies it to every collected item.

Dependencies live in the `sim` dependency group, which is separate from `dev` and therefore
not installed by `uv sync --no-dev` — what the Dockerfile runs. `sim/` is also in
`.dockerignore`, though the Dockerfile's explicit `COPY` list is the real protection.

## What each gate says

Every gate asserts the CORRECT behaviour and currently fails. Each also carries at least one
CONTROL that passes, so a red result can never be blamed on a broken harness.

**G-SURV** — `live.compute_view`'s inner `survival()` opens with `if not opponent_picks:
return 1.0`. At a back-to-back turn there are no rival picks in between, so every player
reads 100% and `grab_now` goes empty. Seat 1 of 8 picks in pairs at 16/17, 32/33, 48/49 —
half its picks. Measured: all 256 available players at survival 1.0 at pick 16; at pick 17
the model discriminates normally.

**G-OCC** — with `IDP_FLEX` filled, occupancy is computed CORRECTLY: the slot is absent
from `unfilled_starting_slots` and every remaining linebacker reads `fills_a_need: False`.
`35e51342` works. `recommend` names two more linebackers anyway.

**G-NEED** — the same root cause as G-OCC, which is the finding. `recommend` sorts by
`(not grab_now, vorp_rank, not fills_need)` and `vorp_rank` is a **unique** integer, so the
third key is never compared. Need binds only through the separate `forced` filter, which
engages once `slack_picks <= 0`. Hold the board fixed and flip the roster from thin-at-RB to
thin-at-WR: the answer does not change.

**G-BYE** — the bye is computed and displayed and consumed by nothing. `draft/usage.py` says
so itself: *"Nothing here enters the sort... never by `board.py`, `value/` or `scoring/`"*,
with a QA invariant enforcing it. So this gate is red **by design of the system**, and
turning it green is a design decision — byes become a ranking input rather than a usage
column — not a bug fix. That distinction is the point of the gate.

## What consumes each signal

```
survival()   -> display only (survival_pct, compare axes).
                BUT grab_now, built from the same `if opponent_picks`
                guard, IS sort key term 1 in recommend.
fills_need   -> display (fills_a_need) + the `forced` filter.
                Sort key term 3, unreachable behind unique vorp_rank.
bye          -> display only (bye_week, bye_collisions, cmd_byes).
                Nothing orders, filters or scores by it.
survives_by  -> urgency.py's The Call, via _urgency_tier, sort key
                term 2 -- but only inside its own top-12 VORP slice.
```

## Rules

- **Do not adjust a gate to change its colour.** If a gate is wrong, it is wrong, and that
  gets said out loud.
- **No network, no historical data, no season replay.** Every state is built by hand. A
  defect you can only see by replaying a season is a defect you cannot put in CI.
- The gates import `src/audible/` and never modify it.

## `probe.py`

Task 2 inventory. Answers one question — can a season replay use audible's own *board*, or
only its *decision logic*? Run `uv run python -m sim.probe`. It builds no replay engine and
makes no network calls.
