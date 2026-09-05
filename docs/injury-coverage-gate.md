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

**G1 FAILS. G2 FAILS. The feature is not built.**

Measured with `audible injury-coverage --league <id>`, top 200 by value, once.

## G1 — roster `status` non-null, per league

| league | non-null | rate | verdict |
|---|---|---|---|
| `sleeper_boyfun` | 200/200 | 100.0% | PASS |
| `espn_davis_drive` | 173/200 | **86.5%** | **FAIL** |

The gate requires both leagues separately, so **G1 fails**.

**Cause, diagnosed:** all 27 missing entries in `espn_davis_drive` are **team defences**.
Sleeper carries a D/ST as a catalog entry keyed by team abbreviation with every status field
null — a defence is not a person and cannot be on IR. `espn_davis_drive` is 8-team, 1-QB,
team-D/ST-only, so 27 of the 32 defences sit inside its top 200 by value. `sleeper_boyfun`
is superflex with deep IDP and no D/ST, so its top 200 is all human and scores 100%.

The 173 that do carry `status` are 173/173 of the *players*. So the shortfall is structural,
not sparse — and it is worth stating plainly that this is the kind of miss a threshold
written before looking at the data is supposed to produce.

## G2 — the negative control: **0 non-Active. FAIL.**

Zero of the 400 top-200 entries across both leagues carry a non-Active `status`. Every
single one reads `Active`.

The gate's own words: *"Zero means the field is dead on the wire and the feature is
worthless — throw it away."*

The field is not literally dead catalog-wide — it takes other values elsewhere:

```
Active                        8,477
Inactive                      3,471
Injured Reserve                 227
None                             45
Physically Unable to Perform      3
Non Football Injury               1
Practice Squad                    1
```

But **not one of those non-Active players is in either top 200**, and that is not an
accident of sampling. A player on IR projects near-zero points, so the value ordering the
board is built from actively selects him out. The chip, as scoped, would have rendered
`Active` on every row it is capable of showing.

## The hand-verification, which is where this stopped being a threshold miss

G2 requires hand-verification. Zero non-Active players were found in the top 200, so the
strict verification set is empty — but the non-Active values that exist *elsewhere* were
checked anyway, because "is this field worth re-scoping the gate around?" is the question a
reader will ask next. The answer is no.

**All seven board-visible `status="Injured Reserve"` players are long retired.** None has
played since 2020.

| player | last played | retired | checked against |
|---|---|---|---|
| Adam Vinatieri (K) | 2019 | 2021-05-26 | NFL.com, Colts.com, Wikipedia |
| Stephen Hauschka (K) | 2020 | 2020-12-04 | Seattle Times, ProFootballRumors |
| Jason Witten (TE) | 2020 | 2021-01-27 | NFL.com, Wikipedia |
| Vernon Davis (TE) | 2019 | 2020-02-03 | Washington Post, ESPN |
| Jordan Reed (TE) | 2020 | 2021-04-20 | NFL.com, Wikipedia |
| Rhett Ellison (TE) | 2019 | 2020-03 | ESPN, Giants.com |
| Garrett Celek (TE) | 2019 | 2020-02-07 | ESPN, SF Chronicle |

Their `news_updated` timestamps are frozen on their retirement announcements — 5 to 7 years
stale — and their ages are frozen there too (the catalog lists Vinatieri at 49; he is 53).

Two details make it worse than mere staleness:

- **The value is not even a faithful last-transaction snapshot.** Hauschka was released for
  performance and never hit IR; Witten played all 16 games in his final season. Sleeper
  parks departed players in a terminal bucket, so `Injured Reserve` cannot be read as
  "was hurt".
- **`status="Active"` is equally uninformative in the other direction.** Tom Brady,
  Gronkowski, Jason Kelce, J.J. Watt and Frank Gore all read `status="Active", active=true`.
  Aaron Donald still reads `team=LAR`; Roethlisberger still reads `team=PIT`.

That last point is the one that matters most here. **G1's 173 "Active" players carry a value
that Tom Brady also carries.** A 95% non-null threshold was satisfiable by a field that is
uniformly meaningless — which is exactly the failure G2 was written to catch, and it caught
it.

## G3 — `injury_status` null-rate, RECORDED

| league | null | rate | populated |
|---|---|---|---|
| `espn_davis_drive` | 167/200 | 83.5% | 32 `Questionable`, 1 `NA` |
| `sleeper_boyfun` | 166/200 | 83.0% | 33 `Questionable`, 1 `NA` |

**The pre-registration got this backwards, and that is worth recording.** The calendar
section above predicted `injury_status` would be "overwhelmingly null" preseason and
therefore should not be gated. It is 83% null — but the 17% that is populated is *not*
absence of data, and it is not an official designation either.

NFL Questionable/Doubtful/Out are issued only during game weeks, with the final designation
due 4:00 p.m. ET Friday. Week 1 2026 opens **Thursday 2026-09-10** (a correction to the
2026-09-09 stated above). **On 2026-09-01 the number of players who can legitimately hold an
NFL "Questionable" is zero.** So the 33 are a vendor-maintained availability flag wearing
the NFL's vocabulary.

Spot-checked, it is directionally real but unreliable in detail: Puka Nacua's psoas issue
was genuine but he had returned to practice on 2026-08-30, two days before the snapshot;
Malik Nabers' `Knee - ACL` is an 11-month-old carryover; body-part strings were stale or
wrong in at least three of six checked; and **all 431 `Questionable` entries catalog-wide
carry a null `injury_start_date`**, so there is no way to tell a fresh flag from an old one.

## Conclusion

Both gated conditions fail, and the diagnosis is worse than the numbers. `status` cannot be
displayed — it is a terminal bucket with 5-to-7-year-old residue on one side and a
meaningless default on the other. `injury_status` is fresher and directionally real, but on
this date it cannot mean what its name implies, and it carries no timestamp with which to
judge it.

Per the rules above, **this is reported and the feature is not built.** No payload join, no
chip. What ships is the extraction, the measurement command, and this record.

## Follow-ups

1. **Re-measure `injury_status` from 2026-09-10**, when Week 1 designations become real. It
   is the only one of the two fields with a plausible future.
2. **Any future gate must exclude team defences from the denominator, or state that it
   includes them.** That choice should be pre-registered, not made after seeing 86.5%.
3. **`status` and `active` are both unusable as liveness signals.** The verification found
   the reliable staleness tell to be `team is None` combined with an ancient `news_updated`
   — worth knowing for any other feature tempted by these fields.
