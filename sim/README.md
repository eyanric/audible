# `sim/` — defect reproduction gates

**These gates were RED on purpose. Four are now green, and that is the deliverable changing
hands rather than the rules changing.**

Defects were found by a human noticing a bad recommendation mid-draft, across three drafts.
This package reproduces them offline, deterministically, from hand-built board and roster
states — so that fixes have something to turn green, and so a further defect of the same
shape cannot hide.

A harness that cannot detect the defects you already know about cannot detect one you do not.

## Running them

```
uv run python -m pytest sim -m slow
```

They are excluded from the default run two independent ways: `testpaths = ["tests"]` does not
reach this directory, and `addopts` carries `-m "not slow"`. The default run must stay fast —
it is what gates draft day. Adding a gate cannot forget the marker: `sim/conftest.py` applies
it to every collected item.

Dependencies live in the `sim` dependency group, separate from `dev` and therefore not
installed by `uv sync --no-dev` — what the Dockerfile runs. `sim/` is also in `.dockerignore`,
though the Dockerfile's explicit `COPY` list is the real protection.

## What each gate says

Every gate asserts the CORRECT behaviour. Each carries at least one CONTROL that passes on
both sides of its fix, so a red can never be blamed on a broken harness and a green can never
be blamed on a relaxed assertion.

**G-OCC** — GREEN since `audible#60`. With `IDP_FLEX` filled, occupancy is computed correctly:
the slot is absent from `unfilled_starting_slots` and every remaining linebacker reads
`fills_a_need: False`. `recommend` used to name two more linebackers anyway.

**G-NEED** — GREEN since `audible#60`, and the same root cause as G-OCC, which was the
finding. `recommend` sorted by `(not grab_now, vorp_rank, not fills_need)` and `vorp_rank` is
a **unique** integer, so the third key was never compared. Hold the board fixed and flip the
roster from thin-at-RB to thin-at-WR: the answer did not change.

**G-CALL** — GREEN since `audible#61`. The same class of defect on the OTHER surface, and the
one Eric actually reads. `recommend` is an MCP tool; the cockpit page renders `the_call`.
`audible#60` moved `recommend` to the composed `effective_score` scalar and left The Call
sorting by raw `vorp_rank`, because `server/state.py::_the_call` rebuilds its candidate rows
by hand and did not name the field. Need was never broken here and the top-12 slice always
held the right answer — measured, at slice position 2 — so neither of the two hypotheses on
offer was correct. What was missing is that `need` is a 2/1/0 bucket that ties at 0 for almost
everyone once the lineup is nearly full, and the ordering then fell through to board rank.

**G-BYE** — GREEN since `audible#61`, on a REBUILT fixture. The merged version gave its
"clean" alternative the same bye as three receivers and the tight end, so that candidate
landed on the roster's already-worst week and cost **9.0** against the collider's **5.0**. It
was asserting a defect, not detecting one. Rebuilt on the control from `tests/test_ordering.py`
where the mechanism discriminates: roster 14.0, shared bye +5.0, unshared bye +1.0.

**G-SURV — RETIRED, because it was wrong.** It asserted `any(grab_now)` at a wheel.
`tests/test_live.py::test_wheel_picks_have_a_one_pick_horizon` asserts the exact opposite
(`assert not any(c.grab_now for c in view.best_available)` at
`opponent_picks_until_horizon == 0`), and `tests/test_server.py` pins a "Two picks on the
clock" header derived from that same zero. Zero opponents between two consecutive picks is
CORRECT: nothing can be taken in between, so nothing is urgent. Making it green would require
redefining the survival horizon, which is wheel pairing. Seat 1 of 8 wheels at 16, 32, 48, 64,
80, 96 and 112, and **joint planning of a wheel pair is a real feature**, not a bug.

## What consumes each signal

```
survival()   -> display only (survival_pct, compare axes).
                grab_now, built from the same `if opponent_picks`
                guard, IS sort key term 1 in recommend. Silent at a
                wheel, and correctly so.
fills_need   -> display (fills_a_need) + the `forced` filter, and
                -need is The Call's LEADING key. It cannot
                discriminate inside a tier, which is what G-CALL is.
bye          -> priced into effective_score via
                ordering.marginal_bye_cost, and therefore into BOTH
                recommend's order and The Call's. Also displayed
                (bye, bye_week, bye_collisions, cmd_byes).
survives_by  -> The Call, via _urgency_tier, sort key term 2 --
                inside its own top-12 VORP slice.
effective_score -> the one scalar both surfaces order by.
                vorp * marginal_start_factor - bye penalty.
```

## Rules

- **Do not adjust a gate to change its colour.** If a gate is wrong, it is wrong, and that
  gets said out loud with evidence — which is what happened to G-SURV and to G-BYE's fixture.
- **No network, no historical data, no season replay.** Every state is built by hand. A defect
  you can only see by replaying a season is a defect you cannot put in CI.
- The gates import `src/audible/` and never modify it.
- Use `harness.current_pick_after` rather than a hand-counted pick number. Passing more player
  ids than the seat owns by `current_pick` silently leaves the surplus ON THE BOARD, and the
  gate then measures a roster it did not build.

## `probe.py`

Replay data inventory. Answers one question — can a season replay use audible's own *board*,
or only its *decision logic*? Run `uv run python -m sim.probe`. It builds no replay engine and
makes no network calls.
