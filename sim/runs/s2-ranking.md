# S2 — the ranking loop

How accurately does Audible's board RANK players against what they actually produced?

Appended per iteration as each lands. Pre-registration first, committed before any number was
computed, because a metric chosen after seeing results is not a metric.

---

## PRE-REGISTRATION

Committed before the harness was built and before any arm was scored.

### the primary metric: round-weighted rank error

For a board ordering and the realised per-game ordering over the same pool:

    RWRE = sum_i w(i) * |board_rank(i) - realised_rank(i)|
           ------------------------------------------------
                          sum_i w(i)

    w(i) = 1 / ceil(board_rank(i) / T)      T = league's team count

**Indexed by BOARD rank, not realised rank.** The board rank is what decides which pick you
spend, so it is the decision-relevant index. Weighting by realised rank would ask a different
question -- "where were the good players?" rather than "what did being wrong cost?".

**Round-decay rather than inverse-rank, and this is a real choice.** `1/i` would say pick 1
costs eight times what pick 8 costs. The market does not price it that way: picks 1 through T
are all first-round assets and are close to interchangeable in cost, while pick T+1 is
categorically cheaper. Round-decay respects the structure the league actually drafts in, and it
has no free parameter to tune. `w` for an 8-team league is 1, 1/2, 1/3 ... across rounds.

**It is fixed for the whole loop.** Any later change to `w` invalidates every earlier
comparison and would have to restate them.

### the pool

Top `num_teams * draft_rounds` by BOARD rank -- 128 for green_hope and danger_zone, 160 for
boyfun. That is the set of players a draft actually consumes; ranking error below it is error
about players nobody rosters.

Realised rank is computed over that same pool, so both orderings are permutations of one set
and the error is well defined. A player the board ranked who recorded no production ranks last,
tied, broken by id for determinism. That is not a special case -- a board that ranked him high
was wrong, and the metric should say so.

### exclusions, and they are gates rather than comments

**K and DEF.** `player_stats` carries no team-defence rows at all in any season, and
`roundtrip.COLUMN_TO_KEY` carries no kicking columns, so both positions realise approximately
zero and would enter as a large block of true zeros predicted as zeros. `sim/weekly.py` already
names them `UNSCOREABLE`. Including them would inflate every arm identically and tell us
nothing.

**ESPN 2023.** Empty -- 129 of 1,128 non-zero -- and its surviving signals are contaminated.
Not substituted, not filled.

**Sleeper 2019 and 2020.** Contaminated; five independent axes break at 2021.

**Sleeper blanked stubs.** Vintage ADP present, projection absent. Filtered, and the count
reported per season.

### seasons available, per arm

Outcomes are pinned for 2019-2025, so 2018 is unusable however good the projection.

    ffa_weighted   2019-2025          seven
    espn           2019-2022, 24, 25  six    (2023 excluded)
    sleeper        2021-2025          five   (2019-20 excluded)
    ffp_ecr        2020-2025          six

Arms are compared only on seasons they share, and the shared window is stated with every
number. An arm that looks better on an easier set of seasons is not better.

### walk-forward

Fit 2019-2022, test 2023-2025. Both halves reported every iteration. Iteration 1 fits nothing
-- it is a measurement -- but the split is still reported so it is established and comparable
against every later iteration that does fit something.

An improvement that appears in-sample and vanishes out-of-sample is REVERTED, whatever the
in-sample number says.

### reported alongside, never optimised against

Spearman over the pool; per-position rank error; top-24 hit rate. If the primary improves while
one of these collapses, that is a finding about the metric and it goes on the page.

### the ordering under test in iteration 1

Board ordering is **projected fantasy points under the league's own rulebook**, which is the
rawest expression of what a source believes. The transform -- VORP, scarcity, tiers -- is
Task 4 and is varied only after the input is settled. Measuring source and transform together
in one iteration would make neither attributable.

`ffp_ecr` is ranks-only and PPR-only. It enters labelled, is not rescored, and its PPR-vs-
standard bias is reported rather than corrected.

---

## PREDICTIONS FOR ITERATION 1

Committed before running. The mechanism matters as much as the direction: a right answer for a
wrong reason is logged as such.

**P1 — FFA weighted ranks best overall among the stat-line arms.** Mechanism: it is a weighted
consensus of many independent sources, and consensus beats its members on average because
member errors are partly independent. FFA's own accuracy study puts FFA Average at 47.4 MAE
cross-position against ESPN last of ten at 86.7.

**P2 — ESPN ranks worst of the three stat-line arms.** Same mechanism, same study. This one has
teeth: **ESPN is what production reads.** If it is confirmed, the cockpit is built on the worst
available input and that is the session's headline. If it is refuted, the study does not
transfer from points-MAE to rank error, which is itself worth knowing.

**P3 — `ffp_ecr` is competitive on rank in the PPR leagues and worst in green_hope.**
Mechanism: it is a ranking natively, so it loses nothing in translation, and ranking is exactly
what this metric measures. But it is PPR-only, and S1 measured its standard-scoring bias as
uncorrectable -- WR and TE flattered by 17-25 rank slots, QB penalised 22-24, with 27-39 of the
top 100 moving more than 20 slots. Green Hope pays zero per reception, so that bias lands
squarely.

**P4 — the spread between arms is widest at TE and narrowest at QB.** Mechanism: QB scoring is
volume-driven and the position is shallow, so every source converges on roughly the same order.
TE is thin, touchdown-dependent and high-variance, so sources disagree most and rank error is
largest for everyone.

**P5 — no arm beats a realised-per-game board.** Trivially true by construction and it is the
harness's own validation (G1), not a finding.

---

## AMENDMENT 1 — the ordering, made before any arm was scored

Found during harness validation (G1), before a single arm number existed. Recorded here rather
than quietly applied, because an amended pre-registration that hides the amendment is worse
than none.

### what was wrong

The pre-registration said the pool is "the set of players a draft actually consumes" AND that
the ordering under test is projected fantasy points. Those two are inconsistent, and the
inconsistency is large. A points-ordered top-128 in green_hope, measured on realised 2021:

    QB 48   RB 40   WR 35   TE 5

against a league that starts EIGHT quarterbacks and eight tight ends. Ordering by raw points in
a 1-QB league puts 48 quarterbacks in a 128-man pool. That is not a pool any draft consumes,
and the pre-registration's own definition rules it out.

### what it becomes

**Both sides are ordered by VORP**, through production's own `compute_vorp`, under the
league's roster structure:

    board side      arm's projected points -> PlayerProjection -> compute_vorp
    realised side   realised per-game points -> PlayerProjection -> compute_vorp

Both are value, one forecast and one realised. A quarterback who scored 27 a game is worth
`27 - QB_replacement` to a roster, not 27, and ordering the realised side by raw points would
systematically punish any board that correctly priced positional scarcity -- which is to say,
it would punish being right.

### why this does not compromise iteration 1

The transform is HELD FIXED and IDENTICAL across every arm. Iteration 1 asks which SOURCE
ranks best; holding one transform constant across sources is exactly what makes that question
answerable. Task 4 varies the transform, with the source then fixed.

Production's `rostered_counts` is known to be wrong at QB -- `_startable_slots(QB) == 1` in a
1-QB league groups it with D/ST and K against a league that rosters 13. It is used unchanged
here anyway, because a defect applied identically to all four arms is common-mode and cannot
move a comparison between them. It is Task 4's subject, not iteration 1's.

`ffp_ecr` is exempt and stays exempt: it is a ranking with no points, so there is nothing to
transform. It enters as its published order.

### what this obliges

G1 is re-validated under the amended ordering. The perfect board is now the realised-VORP
board, and it must still score exactly zero.

---

## HARNESS VALIDATION (G1) — passed, after catching a bug in itself

    league            perfect board        shuffled board
    green_hope        RWRE 0.000000        47.66 +/- 4.10
    danger_zone       RWRE 0.000000        60.45 +/- 4.68
    boyfun            RWRE 0.000000        71.86 +/- 4.95

Spearman 1.0000 and top-24 1.000 on every perfect board; 200 shuffles each.

**G1 earned its place on the first run.** The amended ordering initially gave the PERFECT
board an error of 13.99 instead of 0.0, with every per-position figure reading exactly 0.0.
That shape is diagnostic: VORP and points agree WITHIN a position and differ ACROSS positions
by the replacement level, so a per-position table of zeros beside a non-zero total is a units
bug. The board side was VORP-ordered and the realised side was still ranked on raw points.
Without a known answer to check against it would have shipped as an arm difference.

The pools the transform produces are league-shaped, which is the config-driven claim holding up
under a measurement that did not exist when it was made:

    green_hope   1-QB        RB 57  WR 41  TE 21  QB  9
    danger_zone  1.0/rec     WR 78  RB 48  TE 23  QB 11
    boyfun       superflex   WR 72  RB 53  QB 40  TE 25

Nine quarterbacks against eight starting slots in the 1-QB league; forty in the superflex one.
Three leagues, one transform, three different right answers.

---

## ITERATION 1 — which projection source ranks best

A measurement, not an iteration. Nothing was tuned. Shared seasons across all four arms are
2021, 2022, 2024 and 2025, so fit is 2021-2022 and test is 2024-2025. Nothing is fitted here,
so the fit/test gap is season difficulty rather than overfitting, and it is reported only to
establish the split for later iterations.

### out-of-sample RWRE, with 95% intervals bootstrapped over PLAYERS

Bootstrapping over players is the entire reason the metric is per-player. Two out-of-sample
seasons resolve nothing on their own; 256 to 380 player-observations resolve a great deal.

    green_hope    ffa     20.27  [17.04, 24.25]
                  espn    20.33  [16.67, 24.29]
                  sleeper 21.52  [17.83, 25.92]
                  ecr     30.27  [26.07, 35.09]

    danger_zone   sleeper 24.77  [21.13, 28.78]
                  espn    25.32  [21.86, 29.31]
                  ffa     25.54  [21.83, 29.35]
                  ecr     28.47  [24.66, 32.43]

    boyfun        sleeper 28.79  [24.41, 33.44]
                  espn    30.94  [26.60, 35.89]
                  ffa     32.21  [27.50, 37.03]
                  ecr     35.38  [30.64, 40.48]

### the paired comparison is what decides it

Paired on PLAYER within season -- the same player under two arms -- which removes season
difficulty and player difficulty from the difference. Negative means the first arm is better.

    green_hope    ffa-espn      +0.22  [-0.71, +1.12]   not resolved
                  ffa-sleeper   -0.09  [-1.29, +1.08]   not resolved
                  espn-sleeper  -0.28  [-1.68, +1.17]   not resolved
                  ffa-ecr       -8.12  [-11.32, -4.91]  RESOLVED
                  espn-ecr      -8.38  [-11.82, -5.01]  RESOLVED

    danger_zone   ffa-espn      -0.02  [-1.11, +1.02]   not resolved
                  ffa-sleeper   +1.42  [-0.05, +2.94]   not resolved
                  espn-sleeper  +1.42  [-0.33, +3.30]   not resolved
                  sleeper-ecr   -3.46  [-5.45, -1.57]   RESOLVED

    boyfun        ffa-espn      +0.32  [-0.56, +1.25]   not resolved
                  ffa-sleeper   +3.09  [+1.66, +4.68]   RESOLVED
                  espn-sleeper  +2.86  [+1.13, +4.67]   RESOLVED
                  sleeper-ecr   -5.59  [-7.97, -3.20]   RESOLVED

### what this says, and it is not what was predicted

**The three stat-line sources are indistinguishable in two leagues of three.** Every pairwise
comparison among ffa, espn and sleeper in green_hope and danger_zone crosses zero. The one
resolved stat-line difference in the whole measurement is Sleeper winning boyfun by about three
RWRE against both others.

**Projection source is NOT the largest lever available.** That is the headline and it reframes
what is worth doing next. Swapping ffa for espn moves the board by +0.22 [-0.71, +1.12] in
green_hope -- indistinguishable from nothing -- while the gap between any of them and a random
board is roughly 27 RWRE, and the gap to a perfect board is the whole 20.

### the predictions, scored honestly

**P1 -- "FFA weighted ranks best overall among the stat-line arms." REFUTED.** FFA is nominally
best in green_hope by 0.06 RWRE, which is not a win, and it is the WORST of the three stat-line
arms in both danger_zone and boyfun. The consensus-beats-its-members argument did not survive
contact with rank error.

**P2 -- "ESPN ranks worst of the three stat-line arms." REFUTED, and this is the consequential
one.** ESPN is never worst in any league: second in green_hope by 0.06, second in danger_zone,
second in boyfun. **The FFA accuracy study's points-MAE ordering does not transfer to rank
error.** That study puts ESPN last of ten at 86.7 MAE against FFA Average at 47.4; on ranking,
under three different rulebooks, ESPN is statistically tied with FFA everywhere.

Production reads ESPN. On this measurement that is a defensible choice, not a liability, and
the session's expected headline evaporated. Worth stating plainly: a points-MAE ranking of
sources is not a rank-accuracy ranking of sources, and the two were being conflated.

**P3 -- "ecr competitive in PPR leagues, worst in green_hope." HALF CONFIRMED, and the
mechanism is right.** ECR is resolvably worst in ALL three leagues, so "competitive" is
refuted. But the magnitude tracks the predicted mechanism exactly: it loses by 8.1-8.4 RWRE in
standard green_hope, 2.1-3.5 in danger_zone and 2.1-5.6 in boyfun. The PPR-only bias costs
most where receptions pay zero, which is what S1 measured and what P3 claimed.

And ECR is not uniformly bad -- it is the BEST arm at TE in all three leagues (4.1 / 4.7 / 5.8
against 5.3-7.5 for the rest) and best at RB in green_hope. A native ranking is good at
ordering within a position and bad at interleaving across them, which is exactly the shape you
would expect from a PPR-shaped board that cannot be rescored.

**P4 -- "spread widest at TE, narrowest at QB." HALF REFUTED.** Among the stat-line arms the QB
half holds and holds strongly: green_hope QB spans 2.5-2.6, a spread of 0.1. But the widest
spread is WR (9.2-10.2), not TE (5.3-5.5). The stated mechanism -- that thin, touchdown-driven
positions provoke the most disagreement -- does not survive; receivers are where sources
disagree, and tight ends are where they agree.

Including ECR inverts the QB reading entirely: it errs 5.4 against 2.5-2.6, because a 1-QB PPR
consensus deliberately suppresses quarterbacks and this metric prices them by VORP.

**P5** was the G1 validation and held by construction.

### per-position, out-of-sample

    green_hope   QB: espn 2.5  ffa 2.6  sleeper 2.6  ecr 5.4
                 RB: ecr 7.5   espn 8.0  ffa 8.5     sleeper 8.9
                 WR: ffa 9.2   sleeper 9.8  espn 10.2  ecr 11.2
                 TE: ecr 4.1   ffa 5.3   espn 5.3    sleeper 5.5

    boyfun       QB: sleeper 5.7  ecr 6.6  ffa 7.1   espn 7.9
                 WR: sleeper 11.5  espn 12.5  ffa 13.1  ecr 13.1

Sleeper's boyfun win is concentrated at QB (5.7 against 7.1-7.9) and WR (11.5 against
12.5-13.1). In a SUPERFLEX league quarterback ranking carries far more weight than in a 1-QB
league, which is a mechanism consistent with where the win appears -- and Sleeper is the
platform boyfun actually drafts on.

### stub filter (G5), per season

    season  rows   stubs dropped  unjoined  scored
      2021  3138           1424       497     628
      2022  3138           1209       597     629
      2023  3123            951       681     600
      2024  3125            676       815     597
      2025  3118            284      1044     547

### per-arm, per-season, own full window, green_hope

    ffa      2019 13.6  2020 22.2  2021 19.2  2022 20.7  2023 24.3  2024 22.0  2025 18.6
    espn     2019 17.2  2020 21.9  2021 18.0  2022 21.1     --      2024 23.3  2025 17.3
    sleeper     --         --      2021 18.7  2022 16.3  2023 22.2  2024 22.9  2025 20.1
    ecr         --      2020 24.5  2021 22.6  2022 20.7  2023 26.6  2024 32.2  2025 28.4

Season difficulty dominates arm choice. The spread across seasons within one arm (ffa 13.6 to
24.3) is far larger than the spread across arms within a season. ECR is the exception and it
degrades over time -- 24.5 in 2020 to 28.4 in 2025 -- which nothing here explains.

### disposition

**KEPT: espn as the reference source.** Not because it won -- nothing won -- but because it is
already what production reads, it is tied with every alternative in two leagues and second in
the third, and it carries seven seasons of 45-key stat lines. Changing it would buy a
difference indistinguishable from zero.

**Sleeper is the source for boyfun specifically**, where its advantage is resolved at
+2.86 [+1.13, +4.67] against ESPN. That is a per-league answer, which is what the handoff
anticipated when it said the winner rotates.

**ffp_ecr is not a viable board on its own** and should not become an arm in the ranking loop
except as a labelled TE-ordering comparator, where it is genuinely the best of the four.
