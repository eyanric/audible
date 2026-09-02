# Injury / roster status coverage gate — pre-registered 2026-09-01

Registered **before** any extraction code exists and **before any measurement**, committed
alone, so the thresholds cannot be chosen after seeing the numbers. `git log` on this file
is the evidence it predates the adapter change.

Scope: **Sleeper catalog fields only** — `status`, `injury_status`, `injury_body_part`,
`injury_notes`, `injury_start_date`. The nflverse weekly injury dataset is a later PR; those
reports do not exist until the regular season starts on **2026-09-09**.

---

## The calendar nuance, stated before the thresholds

This is being measured on **2026-09-01**, eight days before Week 1.

NFL **official game-status designations** (`Questionable` / `Doubtful` / `Out`) are produced
by the weekly practice-report cycle, which does not begin until game week. In the first days
of September, `injury_status` being overwhelmingly null is **correct data, not thin data** —
the league has not yet published the thing the field carries.

Gating on `injury_status` now would fail a working feature for a calendar reason and throw
away the half of the data that *is* live. So the two fields are treated differently, and
deliberately:

- **`status`** — the roster/contract state (`Active`, `Injured Reserve`, `PUP`, `NFI`,
  `Suspended`, ...). This is maintained year-round and is the field the chip is actually
  built on. It is **gated**.
- **`injury_status`** — the weekly game-status designation. It is **recorded, not gated**,
  and needs a re-measure once Week 1 designations land.

## The gates

```
G1: roster `status` is non-null for >= 95% of the top 200 by value,
    measured SEPARATELY in espn_davis_drive and in sleeper_boyfun.
    Both leagues must pass on their own; an average across them does not count.

G2: at least 3 players across the two top-200 sets carry a NON-Active `status`,
    and each is hand-verified against a public source. Zero means the field is
    dead on the wire and the feature is worthless -- throw it away.

G3: `injury_status` null-rate is RECORDED, not gated. It becomes a real signal
    from Week 1 and must be re-measured then.
```

### Why G2 exists at all

G1 alone is satisfiable by a field that is uniformly the string `"Active"` for every player
— 100% non-null and carrying exactly zero information. G2 is the negative control: it asks
whether the field ever takes another value, and whether those values are *true*. A field
that cannot disagree with itself is not a signal, which is the same failure the
`verify-offline` work removed from this repo and the same reason `qa-desktop.py`'s `known()`
bucket goes red when an accepted failure starts passing.

Hand-verification is part of G2, not a nicety. `status` being non-Active is only useful if
it is non-Active *for the right reason*; a stale flag on a healthy player is worse than no
flag, because the chip would be actively misleading on a draft night.

## Rules of measurement

- **Measure once.** The first run against the catalog is the number reported, passing or
  failing.
- **A failure is reported, not fixed and re-run.** If G1 or G2 misses, the honest output is
  the raw figure and the work stops there for a human decision.
- **No changes to the extraction between measuring and reporting.**
- Any later change to how `status` is read requires a fresh measurement; these numbers
  describe the catalog as it stood on the measurement date and are not carried forward.

## Follow-up, recorded now so it is not lost

**Re-measure `injury_status` in Week 1 (on or after 2026-09-09).** The G3 null-rate recorded
below is a preseason artefact. Once the weekly practice reports land, `injury_status` becomes
the field that actually matters for a start/sit decision, and it should then be gated on its
own terms rather than merely recorded. That measurement belongs with the nflverse weekly
injury PR.

---

# Result — measured 2026-09-01, once

*(Filled in by `audible injury-coverage` after this file was committed. See the commit
immediately following this one.)*
