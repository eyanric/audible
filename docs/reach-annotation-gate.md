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

# Result — measured 2026-09-02, once

**R1 PASS. R2 FAIL. R3 not yet measurable. The annotation is not built.**

Only DDAFFL could be replayed: Saturday's draft is on 2026-09-05 and has not happened, so
its firing count and R3's per-pick judgment both have to wait. What follows is the whole of
what is measurable today.

## R1 — sensitivity: **PASS**

The Burrow pick fires. Pick 57, value rank 109, delta **+52** against a threshold of 40.

## R2 — specificity: **FAIL. 12 firings, ceiling was 8.**

12 of 128 picks, 9.4%.

```
   pick  rd who                     pos   vrank  delta pos left  next  mine
     53   7 Jayden Daniels          QB       97    +44        4    56
     57   8 Joe Burrow              QB      109    +52        2    72  YES
     68   9 Caleb Williams          QB      136    +68        2    72
     74  10 Rico Dowdle             RB      118    +44        8    88
     77  10 Jonathon Brooks         RB      122    +45        7    88
     85  11 MarShawn Lloyd          RB      312   +227        4    88
     96  12 Kenny Gainwell          RB      179    +83        1   104
     99  13 Jaxson Dart             QB      150    +51        2   104
    100  13 Justin Herbert          QB      144    +44        2   104
    101  13 Matthew Stafford        QB      194    +93        2   104
    106  14 Rachaad White           RB      207   +101        0   120
    124  16 Dallas Goedert          TE      166    +42        5     -
```

Only one of the twelve was Eric's.

## Why it failed, which matters more than the count

**Six of the twelve are quarterbacks, and that is the rule detecting the structure of VORP
rather than detecting a reach.**

In a 1-QB league, replacement level at quarterback sits just below the starter pool, so
every quarterback's VORP collapses toward it. Measured over the top 150 by consensus:

| position | median(value_rank − consensus_rank) |
|---|---|
| **QB** | **+178** |
| RB | −30 |
| WR | −22 |
| TE | −32 |

Quarterbacks sit ~178 slots lower on the value board than on the consensus board; every
other position sits *higher*. The consensus #1 overall player is value rank 27:

```
  Josh Allen               1 ->   27
  Lamar Jackson            2 ->   62
  Drake Maye               3 ->   72
  Jalen Hurts              4 ->   85
  Jayden Daniels           5 ->   97
  Joe Burrow               6 ->  109
```

So `value_rank − current_pick >= 40` fires on **essentially any quarterback taken after about
round four**, regardless of whether that pick was early for that quarterback. The rule as
written announces "someone drafted a QB in a 1-QB league" and dresses it as a reach warning.

This lands on the motivating case too, and it should be said plainly: **the Burrow pick fires
for the same structural reason the other five quarterback picks fire.** A 52-slot gap between
value rank and pick number is what taking any starting quarterback in the middle rounds looks
like on this board. That does not make the pick good — it may well have been a reach — but it
does mean *this measurement is not the evidence for it*, and shipping an annotation that
cannot tell the two apart would put a confident number behind a claim it has not earned.

The remaining six firings are five running backs and a tight end, mostly rounds 10–16, where
value rank is dominated by the junk tail (MarShawn Lloyd at value rank 312, delta +227). Late
in a draft nearly everyone taken is "below where the board ranks them", because the board
ranks 3,302 players and only 128 get drafted.

## What this does not settle

Whether a rule exists that catches Burrow and stays quiet elsewhere. It plainly needs to be
position-relative rather than global — comparing a quarterback against other quarterbacks
rather than against a board where quarterbacks are structurally depressed — and it needs a
floor that excludes the late-round junk tail. Both are real changes to the rule, and under
the rules above they require a fresh pre-registration and a fresh replay, not an edit to
this one.

**Per the pre-registration, the threshold is not adjusted until 8 fit and the second number
reported.** That would describe the tuning rather than the rule, which is the specific
failure this document exists to prevent.

## R3 — not measurable

Requires Saturday's draft and Eric's per-pick judgment afterwards.

## Consequence

Tuesday's draft runs on the board as it is — the same board that has already run two drafts.
Nothing was wired into the cockpit, so there is nothing to roll back.
