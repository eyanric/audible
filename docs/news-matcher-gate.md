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
