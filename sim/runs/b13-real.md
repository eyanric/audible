# B13 — measure the cockpit that is actually running

Base `main` at 381099ef. Branch `feat/real-board`.
Runs: `b13-{ffc,mfl12,mfl8}.json`, each identical to
`b10-{ffc,mfl12,mfl8}.json` except `real_board`.

## The defect this session exists to fix

`sim/seat.board_from_season` builds the seat a board whose
value is linear in ADP rank. Its order IS the market's
order. Every `real` number from B2 through B12 was
measured on it, so the arm named "the cockpit's own path"
could not respond to anything either audible#77 or
audible#78 changed. Both sessions spent themselves moving
replacement level and both reported `real` unmoved, and
neither could say whether that was a result or a wiring
defect.

It was a wiring defect. Perturbing the depth table by
audible#78's own iteration 2 (QB 14, RB 43, WR 35, TE 20):

```
  season   market board        production board
  2023     192/192 unchanged    30/192 unchanged
  2024     180/180 unchanged    38/180 unchanged
```

The largest single move is a quarterback, Kyler Murray
127 -> 79 in 2024 — the same direction and magnitude as
the live 2026 `espn_davis_drive` measurement audible#77
recorded, Josh Allen 28 -> 14 and Joe Burrow 108 -> 63.
`sim/test_g_b13.py` gates both halves of that table.

## What `real_board = "production"` is

`build_board_from_lines` -> `compute_vorp` ->
`effective_score`, over FFA's pinned vintage projections.
`sim/boards.build` already constructed that object and
threw it away after reading rank columns off it. Nothing
extra is built.

WHY THE OBJECTION IN `board_from_season` DOES NOT REACH
IT. That docstring refuses `compute_vorp` over the linear
ADP curve, on measured evidence — TE replacement 48.4
against WR 147.3 in 2024, three tight ends above
McCaffrey, the seat drafting five of them — and ends "there
are none [no real projections] for any of these seasons".
B5 falsified that clause. The objection is specific to
feeding the value engine a manufactured curve and it still
stands; the production path over real vintage projections
is a case it never covered. Preflight refuses
`real_board = "production"` under `projection =
"walkforward"` for exactly that reason.

## The board is a running-back monoculture

Not a side note. Verified on all five seasons:

```
  season   production top 24        market top 24
  2021     RB 21  WR 2  TE 1        RB 15  WR 7
  2022     RB 22  WR 1  TE 1        RB 14  WR 8
  2023     RB 20  WR 2  TE 1 QB 1   RB 9   WR 11  QB 3
  2024     RB 22  WR 2               RB 12  WR 12
  2025     RB 23  WR 1               RB 13  WR 9   QB 2
```

The first TWELVE slots are running backs in every one of
the five seasons. Replacement lands at RB 72-81 against WR
122-135, because this league pays nothing per reception
and the receiver pool is deep and flat while there are
about 32 startable backs.

This is the same class of positional artifact
`board_from_season` records for a linear curve, with the
positions swapped, and it is `audible_transform`'s known
ordering rather than anything new. It is also the object
the live cockpit serves, so it is a PRODUCT finding and
not a harness one.

## What the seat does with it

`real` composition per team, b10 -> b13, ffc_12:

```
  QB 1.05->1.04  RB 5.12->7.46  WR 5.02->2.99
  TE 2.80->2.51  K 1.00->1.01  DEF 1.01->1.00
```

RB +2.34 [+1.73,+2.95] and WR -2.03 [-2.57,-1.51], both
excluding zero, and the same in all three markets. So the
overlay absorbs the monoculture partially and not fully.

## The numbers, and none of them is a result

`real`, production board against market board. NOT paired
in the config's original wording; the review corrected
that — b10 and b13 share seasons, seeds, market, pins, fit
and prior, and every stream derives from the seed, so the
per-unit paired difference is the defensible estimator.
It makes no difference to the conclusion:

```
  market   delta    clustered interval      LOO
  ffc_12   +31.49  [ -67.00, +129.99]   +2.19 w/o 2025
  mfl_12   +31.69  [ -19.57,  +82.95]   +16.5..+43.6
  mfl_8    +26.46  [ -67.51, +120.43]   -3.48 w/o 2024
```

Two of the three headlines are ONE SEASON. mfl_8 changes
SIGN when 2024 is dropped. Nothing here is shown.

`real` against the arms the handoff named, b13:

```
                        ffc_12    mfl_12    mfl_8
  real - adp            +49.3     +77.8     +53.7
  real - points_greedy +207.1    +197.8    +184.9
  real - ffa_baseline   +18.0     +47.2     +35.7
  real - transform      +84.7    +116.0     +82.2
```

NINE OF NINE INTERVALS INCLUDE ZERO. `real - adp` is the
one that decides whether any of this is evidence, and it
does not exclude zero in any market. `real -
ffa_baseline` flips sign on ffc_12 when either 2022 or
2025 is dropped. `real - audible_transform` is the only
one that holds its sign across every leave-one-out fold
(+60.7..+116.2, +85.1..+151.7, +53.4..+111.4) and its
interval still includes zero.

The direction is worth stating anyway, because it reverses
what audible#77 and audible#78 were chasing: the transform
sits 47 to 67 points BEHIND `ffa_baseline`, and the
cockpit's actual path — same board, plus the overlay —
sits ahead of it. Not resolvably. But the gap those two
sessions were closing was measured on an arm that is not
the cockpit.

## The leak gates, and a pass that is not one

```
            b10 shuffle   b13 shuffle   b13 real-shuffle
  ffc_12       +54.6        -103.2      +286.6 [+150.7,+422.5]
  mfl_12       +19.3        -226.8      +367.7 [+289.9,+445.5]
  mfl_8        +27.6        -179.7      +302.0 [+222.8,+381.1]
```

G6b passes resolvably everywhere. READ THAT CAREFULLY. Of
the widening in `real - shuffle`, 83.4% / 88.6% / 88.7% is
the CONTROL ARM COLLAPSING, not the seat improving — the
`real` component is the same non-significant +31/+32/+26
above. Shuffling a board with real values in it is far
more destructive than shuffling a relabelling of ADP.

Two consequences, both found by review:

  * `b10-mfl8` FAILS G6b (+68.2 [-28.3,+164.6]) and
    `b13-mfl8` passes. That flip is entirely the degraded
    control. B10 diagnosed mfl_8's G6b as a season-count
    power shortfall and this does not resolve it.
  * `shuffle - bot` went from >= 0 to -99.1 / -248.8 /
    -169.8, all excluding zero. The artifact's own
    `leak_decomposition.reading` asserted "the shuffle arm
    keeps audible's structure and only loses its value
    ordering", which its numbers contradict. The reading
    is now derived from the term's sign.

`real - shuffle` in b13 is NOT comparable to any prior
run's number.

G6d: `LEAK_CEILING = 150.0` is derived entirely from "the
board is a monotone transform of ADP rank, so there is no
better ordering of it to find" — the property this session
removes. Its failure string would have been contradicted
by the same artifact's `board_vs_adp` (pearson 0.78, 1
exact of 128). The production seat now gets the MEASURED
perfect-foresight bound the board arms already get:
`real - adp` +49/+78/+54 against `ceiling - adp`
+300.4/+410.1/+385.4.

G6a fails on mfl_12 at +22.0 [+6.7,+37.4]. PRE-EXISTING
and byte-identical to b8, b9 and b10; diagnosed in
`b9-classifier.md` Task 3.

## The cheap-harvest hypothesis is refuted

The obvious objection is that the seat is only winning
because the room is ADP bots who will not take those
running backs, so it harvests them cheaply. Three
measurements say no:

```
  seat mean obtained ADP rank   62.02 -> 61.91
  opponents                     69.04 -> 68.92
  total RBs taken per draft     40.52 -> 41.61
```

The seat's price is flat and the room does not leave a
pool of backs on the table — the seat's +2.34 RBs mostly
displace opponents' RBs. Position-specific, the seat's
running backs went from 9.6 ranks EARLIER than opponents'
to 5.2 ranks LATER. And the RB-heavy ordering by itself
loses: `audible_transform` on the same board posts
`transform - adp` of -35.4 / -38.2 / -28.5. The
monoculture is not what produces `real`'s number.

## UNSTARTABLE_FACTOR, reported separately

`ordering.UNSTARTABLE_FACTOR = 0.05` patched to 1.0,
ffc_12, production board, paired on 300 identical units:

```
  changed the draft in 242 of 300 units
  QB per team          1.037 -> 2.053
  wasted_roster_slots  0.050 -> 1.067   +1.02 [+0.26,+1.78]
  unfillable_byes      2.390 -> 2.170   -0.22 [-0.33,-0.11]
  points               +5.92 [-18.61,+30.45]
```

It does exactly the structural job it claims — without it
the seat drafts a second unplayable quarterback in a 1-QB
league and wastes a roster slot per team — and that effect
resolves. Its POINTS effect does not. It is also not
structurally free: disabling it IMPROVES unfillable byes
by a resolvable amount, because the wasted slot would
otherwise have gone to a player with a colliding bye.

## Structural, reported and not used to veto

`real`, b10 -> b13:

```
  ffc_12  wasted 0.057->0.050  surplus 5.000->5.217
          byes 2.360->2.390
  mfl_12  wasted 0.127->0.087  surplus 5.017->5.143
          byes 2.423->2.493
  mfl_8   wasted 0.023->0.050  surplus 5.000->5.150
          byes 2.240->2.713
```

Only two resolve: mfl_8's `positional_surplus` +0.15
[+0.02,+0.28], unfavourable. mfl_8's byes +0.47 has a
large point estimate and an interval that includes zero.

## Cap fitting, the G2 enumeration owed by Task 1

Every consumer of `fit.caps`: `boards.greedy` (every board
arm), `seat._adp_greedy`, `room._best` and the off-board
plan, `artifact.fit_block`, and two test mirrors.

Positions whose cap rests on exactly ONE team-season in
forty — the property that made the b4 control saturate:

```
  K    cap 2   {1: 39, 2: 1}
  QB   cap 3   {1: 16, 2: 23, 3: 1}
  TE   cap 3   {1: 29, 2: 10, 3: 1}
  DEF  cap 2   {1: 38, 2: 2}          two, not one
  RB   cap 7   {...7: 2}              two
  WR   cap 8   {...8: 2}              two
```

THREE positions, not one. The commit that fixed the b4
control named only QB. `points_greedy` sits on K's n=1 cap
in twelve committed runs, so a gate written in the QB
shape on kickers would be equally vacuous today; TE's is
reachable (`scarcity_only` hits 3.0 on a short run).
`sim/test_g_room.py:435` asserts `caps[pos] == max(hist)`,
which enshrines the n=1 fit rather than guarding it. Cap
fitting is NOT changed here — the handoff forbids changing
it in the same iteration as the gate.

Worth naming: `real` drafts RB 7.40-7.46 against a cap of
7, and `legacy` 3.07 against a QB cap of 3. The cap is
hard only on the `greedy` / `_adp_greedy` / `_best` paths;
the audible seat chooser is not cap-checked. A gate in the
QB shape written against `real` would compare to a ceiling
`real` can cross.

## Provenance limit, stated because it is real

`b13-ffc-nounstartable.json` carries the SAME `run` name,
`config_hash` and `code_sha` as `b13-ffc.json` — only
`content_digest` differs. `code_sha` records THAT the tree
was dirty, never WHAT was dirty, so an artifact produced
under a patched module constant is not distinguishable
from a clean one by its own provenance. That ablation is
not committed for exactly this reason.
