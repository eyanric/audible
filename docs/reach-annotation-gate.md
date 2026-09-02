# Reach annotation — pre-registered 2026-09-02

Written and committed **before the replay was run**, so the firing rule and the thresholds
cannot be chosen to flatter the output. `git log` on this file is the evidence it predates
the annotation and the replay.

The subject is the DDAFFL draft's worst outcome: **Joe Burrow taken at pick 57 against value
rank 109** — a 52-slot reach the board could not flag because it ranks players in a vacuum.

---

## The firing rule, fixed here

```
delta = value_rank - current_pick
FIRE when delta >= 40
```

That is the whole rule. It is deliberately one comparison over two numbers the payload
already carries.

**Why 40, chosen before looking at any distribution.** A 40-slot gap is five rounds in an
8-team league and four in a 10-team one. Firing at that threshold says: *the board expected
this player to still be available four or five rounds from now.* That is a substantive claim
about the market rather than a rounding artifact. Below roughly two rounds the gap is inside
the noise between any two people's boards and marking it would be marking nothing.

**What the rule deliberately does NOT include.** Survival is displayed but does not gate the
firing. It is the better decision input — "will he be there at my next pick" beats "is this
early" — but folding it into the trigger would make the threshold two coupled knobs instead
of one, and a two-knob rule tuned after seeing the output is not a pre-registration. Survival
earns its place as a stated fact, not as a filter.

## The gates

```
R1 sensitivity: the annotation fires on the Burrow pick (DDAFFL, pick 57, value rank 109).

R2 specificity: across each completed draft, it fires on NO MORE THAN 8 PICKS.

R3 honesty:     for every pick it fires on in Saturday's draft, Eric judges after the fact
                whether the flag was right. Recorded per pick, not in aggregate.
```

### Why N = 8, justified before looking

Both drafts are 16 rounds. **8 firings is one every two rounds.** At that rate a firing is
still an event when it happens in round 12 — the reader has not been trained to scroll past
it — and its *absence* still carries information, which is the property that dies first when
a marker becomes common.

As a fraction: 8 of DDAFFL's 128 picks is 6.3%; 8 of Danger Zone's 160 is 5.0%. Above roughly
one in ten, a marker stops reading as "look at this" and starts reading as decoration. Eight
sits comfortably under that on both drafts while still leaving room for the genuine article —
a draft really can contain several reaches.

The measurement is over **every pick in the draft, not only Eric's**. That is the harsher
test: Eric makes 16 of 128 picks, so measuring only his would let a rule that fires
constantly on other teams' picks pass while being unusable in practice, since the annotation
renders on whichever row is highlighted rather than only on rows he ends up taking.

**R2 is the gate that decides this feature.** R1 is nearly free — any threshold loose enough
to catch a 52-slot reach will catch it. The real question is whether a threshold that catches
Burrow stays quiet across the other 127 picks. If it cannot, the feature is not ready, and
that is a real and acceptable outcome.

## Rules of measurement

- **Measure once.** The first replay against each draft is the number reported, passing or
  failing.
- **A failure is reported, not tuned away.** If R2 misses, the honest output is the raw count
  and the firing list. Adjusting the threshold until eight fit and reporting *that* number
  describes the tuning, not the rule.
- **No change to the firing rule between committing this file and running the replay.**
- Any later change to the threshold requires a fresh replay; these numbers describe the rule
  as written above and are not carried forward.

## What the annotation shows when it fires

Facts, and then it stops. No recommendation, no "don't", no colour scale implying a judgment
the numbers do not carry — the same rule the injury chip and the bye collision warning follow.

1. **value rank, current pick, and the delta** — the reach itself
2. **players remaining above replacement at that position** — `vorp > 0`, counted over the
   available board. Not a new model: VORP is already `points - replacement_points`, so
   "above replacement" is a filter over a number the board has carried all along.
3. **the pick number of Eric's next turn** — `clock.my_next_pick`
4. **survival: the existing model's read on whether this player lasts until that pick**

Three of the four are already in `/api/state`. The fourth is a count. Nothing here ranks
players, and nothing here computes a projection.

## Inertness

Display only. The board must be byte-identical with the annotation present and absent, and
nothing under `value/`, `scoring/` or `providers/` may import it — the same two guarantees
the bye join carries, asserted the same way.

---

# Result — measured 2026-09-02

*(Filled in by the replay, after this file was committed. See the commit that follows.)*
