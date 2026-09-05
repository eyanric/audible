# News matcher gate — pre-registered 2026-08-31

Registered **before** any matcher code exists, and committed alone, so the numbers
cannot be chosen after seeing them.

## The gates

```
G1 (recall):    >= 90% of collected items whose title contains the name of a player
                rostered in espn_davis_drive resolve to the correct sleeper player_id.
G2 (precision): 0 false matches in a hand-audited sample of 100 matched items.
G3 (sources):   `audible news probe` returns >= 2 feeds serving valid XML with at least
                one item younger than 24h.
```

Sample: >= 48h of continuously collected items.
Numbers are recorded once, before any tuning. If G1 or G2 fails, report and stop.

## Why this exists

The failure it prevents is re-metricking: build a matcher, measure, dislike the number,
adjust the matcher, measure again, and report only the second number. That produces a
figure which describes the tuning rather than the matcher, and nobody downstream can tell.

So the threshold is fixed here, in its own commit, with nothing else in it. `git log` on
this file is the evidence that it predates `news/entities.py`.

## Rules of measurement

- **Measure once.** The first run against the sample is the number that gets reported,
  passing or failing.
- **A failure is reported, not fixed and re-run.** If G1 or G2 misses, the honest output is
  the raw figure plus the failing cases, and the work stops there for a human decision.
- **No changes to the matcher between collecting the sample and measuring it.**
- Any later change to the matcher requires a fresh sample; the recorded numbers describe
  the matcher as it was at measurement time and are not carried forward.

## On the 48h sample

The intent is a sample wide enough that one slow news day cannot flatter the result. Two
readings are possible and they are not equivalent:

- **48h of wall-clock collection** — polling continuously for two days.
- **items spanning >= 48h of publication time** — a single fetch, since most feeds serve a
  backlog covering several days.

The second is achievable in one session and the first is not. Whichever is used **must be
stated with the numbers**, because a 48h span from one fetch is a weaker sample than 48h of
polling: it cannot show whether the matcher degrades on items that arrive later, and it
inherits whatever the feed chose to retain.

---

# Result — measured 2026-08-30, once

Sample: **114 items, single fetch, spanning 89.5h of publication time.** This is the
*second* of the two readings above — the weaker one. It is not 48h of wall-clock polling,
and it therefore cannot show whether the matcher degrades on items that arrive later.

## G3 — sources: **PASS**

6 of 7 registered feeds returned 200 with valid XML and an item younger than 24h.
`fantasypros` returned 404 and is disabled in the registry rather than deleted, so the next
probe re-checks it.

## G1 — recall: **PASS, 91.7%**

Ground truth was computed independently of the matcher (normalised title token-run
containment against board player names), because deriving it from the matcher would make
the measurement circular.

```
eligible (title names a board player) : 24
resolved to the CORRECT player_id     : 22
resolved to the WRONG player_id       :  2
not resolved at all                   :  0
G1 = 22/24 = 91.7%   (threshold 90%)
```

Both misses are multi-player headlines where the matcher returned a different player who
was *also* named in the title:

- `Ranking the 12 most surprising NFL roster cuts: Will Levis, Jaydon Blue...` — ground
  truth wanted Jaydon Blue; the matcher returned Will Levis, who is also in the title.
- `Ranking NFL's 15 greatest comebacks from retirement: Where Aaron Donald...` — ground
  truth wanted Tom Brady; the matcher returned Aaron Donald, also in the title.

Neither is a wrong attribution in the damaging sense — no item was tied to a player it does
not mention. The real limitation they expose is that **one item resolves to at most one
player**, which is a design limit worth revisiting, not a tuning failure.

## G2 — precision: **FAIL**

The gate requires 0 false matches in a hand-audited 100. Two things must be said:

1. **The sample was short.** Only **65** matched items existed to audit, not 100. The gate
   cannot be satisfied by this sample even in principle.
2. **The audit found a false match at position 27 of 65.**

```
title  : NFL waiver wire rules and the Eagles' position in the claiming order
matched: "Duplicate Player"  (player_id for an inactive PHI CB placeholder)
via    : surname_team  -- surname "Player" + "Eagles" corroborating PHI
```

The Sleeper catalog contains **135 junk placeholder entries** with names like
`Duplicate Player`. Their surnames are ordinary English words, so any headline containing
that word plus a team name can produce a confident, wrong attribution.

This is exactly the failure class the matcher's own docstring calls out as the one that
matters: not a gap, but disinformation.

**Per the rules above, this is reported and not fixed.** The obvious repair — drop
non-active and placeholder catalog entries from the index — is deliberately *not* applied
in this PR, because applying it and re-running would produce a number describing the tuning
rather than the matcher. It is recorded instead as a strict-xfail test,
`tests/news/test_entities.py::test_junk_catalog_entries_must_not_be_matchable`, which will
fail loudly the moment it starts passing.

**A fresh sample is required after any fix.** The numbers above describe the matcher as it
stood on 2026-08-30 and are not carried forward.
