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
