# Pre-registration — the retroactive redraft

**Committed before the redraft was implemented and before any redraft number existed.** Git
history is the timestamp. No metric changes after results; a loss is reported as plainly as
a win.

## Task 1 gate — passed, all five seasons usable

Source: Fantasy Football Calculator ADP, standard scoring, one cached call per season.

| year | drafts | sample range | week-1 kickoff | verdict |
|---|---|---|---|---|
| 2021 | 2,656 | 2021-08-28 → 2021-09-01 | 2021-09-09 | **USABLE** |
| 2022 | 2,112 | 2022-08-31 → 2022-09-04 | 2022-09-08 | **USABLE** |
| 2023 | 1,104 | 2023-08-30 → 2023-09-01 | 2023-09-07 | **USABLE** |
| 2024 | 742 | 2024-08-30 → 2024-09-01 | 2024-09-05 | **USABLE** |
| 2025 | 2,017 | 2025-08-25 → 2025-09-01 | 2025-09-04 | **USABLE** |

Every sample window closes before that season's first regular-season kickoff (kickoffs taken
from nflverse schedules, not from memory).

### Preseason sanity check

The first cut of this check used "is he ranked top 60" and was **wrong** — it flagged Michael
Badgley, a kicker, whose ADP of 157 is exactly where kickers belong. Recorded because the
corrected test is the one that matters.

The right question is whether players who barely played are still ranked **high**. A snapshot
assembled after the fact could not do that.

| year | Spearman(ADP order, games played) | top-30 pick who played ≤4 games |
|---|---|---|
| 2021 | +0.037 | #29 Chris Carson (ADP 28.0) → 4 games |
| 2022 | +0.100 | #18 Javonte Williams (ADP 15.8) → 4 games |
| 2023 | −0.200 | **#3 Nick Chubb (ADP 3.1) → 2 games** |
| 2024 | +0.023 | **#1 Christian McCaffrey (ADP 1.2) → 4 games** |
| 2025 | −0.041 | #16 Malik Nabers (ADP 14.8) → 4 games |

A contaminated snapshot would show a strongly positive correlation. All five are ≈zero.
McCaffrey at ADP 1.2 in a season he played four games is conclusive on its own.

### A source caveat, found by checking rather than assuming

**The `teams` parameter is silently ignored.** `teams=8` and `teams=12` return byte-identical
payloads with `meta.teams = 12`. This ADP is **12-team**, not 8-team, and no 8-team variant is
available from this endpoint. Consequences are known and bounded: ADP order ≈ market rank
regardless of league size (measured earlier at mean |adp − rank| = 0.42 over the top 200), but
12-team rooms draft QB/TE/K/D-ST earlier than 8-team rooms do. That bias is carried into
Audible's ordering and is reported, not corrected.

## The gate

**Primary: Audible beats Eric's actual roster in ≥4 of the 5 usable seasons.**

**A season counts as a win only if the margin exceeds 50 actual points.** Fixed in advance and
justified by scale rather than by taste: 50 points is roughly one starter-quality upgrade
sustained across a season — the measured gap between a startable RB and his wire replacement
is ~3.2 points a week, or ~54 points over 17 weeks. A margin below that is not a draft
difference, it is noise in how one player's season happened to go.

Effect size reported in **points** and as a **share of season total**, both.

## Method, fixed now

- Seven other seats keep their **actual picks** from the real 6012 draft, in their actual order.
- Audible picks at Eric's actual pick numbers, choosing only from players genuinely available
  at that moment.
- Audible uses **only** that year's FFC standard ADP plus this league's replacement-level and
  roster-construction logic. No projections, no hindsight.
- **Collision rule, fixed in advance:** if an opponent's actual pick was already taken by
  Audible, that opponent takes the best player still available by FFC ADP. Deterministic, and
  the minimum repair that keeps the rest of the draft real.
- Both rosters scored on **actual points under that season's own rules** (standard).

## Task 4, also pre-registered

The same procedure replacing **each of the eight managers in turn**, so Audible's record is
reported against every seat and not only against Eric. One manager's five seasons is five
observations; eight managers' is forty, and the difference between those two claims is the
point of running it.

## Not being done

- No tuning, no weight search, no metric redefinition after results.
- Nothing enters the sort on this result without separate review.
