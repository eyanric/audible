# audible — carry-forward state

**Read this first. Rewrite it as your final commit.**

This file exists because the previous carry-forward lived outside the repo, so the session that
needed to update it could not reach it. Everything a new session needs to avoid re-deriving
settled facts belongs here, in the repo, versioned with the code it describes.

Rules for editing:

- **Verified facts only.** If it was measured against a live API, say so and give the number.
- **Record the decision, not just the finding.** "Flagged not fixed" is the useful half.
- **Delete what stops being true.** A stale line here is worse than no line.

---

## DRAFT: **Sunday 30 August, ~19:00.** ESPN league 6012. Seat 8.

> **The date changed and the old one is still written in places.** This file previously said
> *Friday 28 August, 8:30*; the current instruction says **Sunday 30 August, ~7pm**. Sunday is
> what everything below assumes. If Friday is right, everything moves two days earlier and the
> freeze has already passed — confirm before trusting a single date here.

**Code freeze: the day before, whichever it is.** No merges, no rebuilds, no config edits after.

---

## STOP: the cluster is serving LEAGUE A. Fix this before anything else.

`http://192.168.1.110` — the container behind `mcp-audible.havenhomelab.org` — is running
**`sleeper_boyfun`**, not League B. Measured 2026-08-25:

```
/healthz     players 7620                  (League B is 3302)
             draft_id 1361543954792742912  (a Sleeper id; League B's is "6012")
/api/state   league.key "sleeper_boyfun", num_teams 10, superflex true, rounds 18
draft_status unfilled [...'SUPER_FLEX','K','IDP_FLEX'],  my_slot None
```

This is the failure A3 predicted and recorded as **closed**. The image bakes
`--league sleeper_boyfun` as its default command; `scripts/draft-day.cmd` was fixed to
override it; **the long-running cluster container was never restarted with that override.**
The launcher fix only ever applied to the local container on the Windows box — and the
cluster is what the public MCP hostname fronts.

So on the 30th, the cockpit opened from `draft-day.cmd` is correct, while **anything asked
through the public MCP endpoint answers off a 10-team superflex IDP board.** It will not
error. It will answer confidently and wrongly, which is worse.

Restart it with the league named, exactly as the launcher does:

```
audible serve --league espn_davis_drive --host 0.0.0.0 --port 8080
```

Then verify, and **do not trust a 200**:

```bash
curl -s http://192.168.1.110/api/state | grep -o '"key": "[^"]*"'   # must say espn_davis_drive
```

Full detail, plus the two OAuth soft spots, is in `docs/runbook-draft-day.md`.

---

## What the pre-draft sprint changed (2026-08-25)

Five PRs, all merged, all green. Suite **224 passing**, `ruff` clean.

### P1.1 — replacement level is the waiver wire, not the starter line (#18)

The board ranked the top D/ST **33rd overall** and D/ST and K were **all eleven** of its
biggest "market underpricing" targets, in a league that drafts them last.

The brief's first hypothesis was falsified: replacement was already landing at exactly
D/ST9 and K9. The defect was on the other side of the comparison. Replacement was computed
as "best non-starter", which is the waiver wire only in a league with **no bench**. League B
drafts 16 rounds against 9 starting slots, so 56 of its 128 picks are bench players who are
not on the wire. That set the RB baseline at RB17 and WR at WR25 when the real waiver line
is around RB35 and WR52 — compressing every skill-position VORP by 30–50 points, and **not**
compressing D/ST or K, because nobody rosters a backup D/ST.

The damning number: the board wanted **24 D/ST and 22 K inside 128 picks**. The market's
first 128 hold zero.

**Allocating the bench by VORP is exactly wrong, and it was measured.** Replacement is
*defined* as the best unrostered player, so VORP is 0.0 at every position's own baseline and
ranking non-starters by it ranks them by how FLAT the curve is — and K and D/ST are the
flattest positions in football. It is also self-confirming: each D/ST stashed pushes D/ST
replacement deeper, raising D/ST VORP. It converged on rostering 24 D/ST. Bench depth
instead goes to positions a team could start more than one of, split by starter demand.

Validated against ADP, the only ground truth for how many of each position gets drafted:

| | RB | WR | QB | TE | DEF | K |
|---|---|---|---|---|---|---|
| market's first 128 | 43 | 53 | 16 | 16 | 0 | 0 |
| after | 35 | 52 | 8 | 17 | 8 | 8 |

**First D/ST 33 → 80. First K 43 → 94.**

**League A is deliberately unchanged**, and its TOML says why: the same allocation pushes
its QB replacement to QB36 against ~32 real NFL starters (QB36 projects 36 points) and
produces 13 quarterbacks in the top 15 — the junk-tail pathology already recorded against
scarcity/VONA. Superflex is what breaks it. Every supply guard that fixes it is a threshold
picked to make that board look right. **Re-open with a supply rule derived from something.**

### Scoring correction — verified applied, now guarded (#19)

**It was already correct everywhere.** AST scan over every `scoring_for` / `config.scoring`
reference in `src/`: eight call sites, zero zero-arg. All four board surfaces resolve to one
warmed board whose every number descends from `board.py`'s single
`config.scoring_for(primary)`. Measured end to end, a 60-catch back projects **176.0**
against **206.0** off the base table — exactly the 30 points a season the config claims.

What was missing was any test that would notice if that stopped being true.

- **`scoring_for(position)` no longer defaults to `None`.** The default *was* the bug class:
  it returned the base table, which pays a running back 0.5 a catch in a league that pays
  him nothing. Every call site already passed a position. Now it is a type error.
- A cross-surface test drives one pass-catching back through the real board assembly and out
  through `best_available`, `recommend`, `compare` and `player_lookup` over a real FastMCP
  client, asserting the four agree **and that what they agree on moves** when
  `scoring_by_position` is stripped. Agreement alone proves nothing.
- The ESPN adapter's end-to-end test asserted a QB, a kicker and a D/ST — **none of the three
  positions the rule touches** — so it passed unchanged with `scoring_by_position` deleted
  while every back ran ~34 points high (Gibbs 297.393 vs 331.298). Fixed.
- `recommend` interpolated `survival_pct` with no None check, so unpriced players read
  **"None% to last the 5 rival picks"**. Unpriced is the common case late in a draft.

### P0 — the cockpit is drivable with a thumb (#20)

The previous session drove the page in a real browser and found it interactive. All true,
and all on a **desktop viewport**. Driven again at iPhone width with simulated touch, the
same page is not usable. That gap was the whole P0.

| measured at 393px | before | after |
|---|---|---|
| mark button | **18×18**, `border-color: rgba(0,0,0,0)`, revealed by `:hover` — a finger never hovers | **44×44**, solid border, always visible |
| row height | 23px | 45px |
| controls under 44px | **155** | 3 |
| roster panel | y = 970px, off-screen | one tap away |
| runs & cliffs | y = 1373px, off-screen | one tap away |

Correcting the earlier note: the page does **not** clip horizontally. The `max-width:900px`
fallback already makes it *fit* a phone; it does not make it *drivable* on one.

Keyed on `hover:none`, not width — the question is whether a finger is driving. A fixed
thumb bar switches sections and carries its own Undo, disabled rather than hidden. Selection
moved `mousedown` → `pointerdown`; iOS drops synthesised mouse events when a touch becomes a
scroll.

Verified by **driving it** against the live board: tap-to-mark, tap-to-undo, and all three
section switches pass, no console errors. Desktop re-checked at 1600×900 and is unchanged.

One bug it found in itself: the bar's own `display:none` was declared *after* the media query
that sets `display:flex`, so source order won and it rendered 0×0 — present in the DOM,
correct in every inspection, every tap landing on the board behind it. The test pins the order.

### recommend respects the bench (#22)

Found by the full dry run. `recommend` filtered to players who fill an unfilled **starting**
slot, with no concept of the bench. Six picks in, FLEX was filled by a backup tight end *the
tool itself had recommended*, so every RB, WR and TE read `fills_need: False` and the best
remaining "need" was the top defence at VORP #80 — with Mike Evans at #34.

Now arithmetic, no threshold: count the picks still held, subtract the slots still empty.
While that slack is positive an empty slot is a preference; at zero every remaining pick is
committed and only need-fillers qualify. `draft_status` reports both numbers.

**Second defect found while fixing it:** `DraftSession.rounds` defaulted to **18** — League
A's number, hardcoded in shared logic. League B drafts 16, and an 18-round clock overstates
the picks remaining by two, which is the difference between filling the last starting slots
and finishing without a kicker (reproduced). Rounds now seed from a structural
`draft_rounds` config field, still overridden by live sync.

---

## TASK 5 — the full dry run, and what it says

8 teams, 16 rounds, 128 picks, driven entirely through the MCP tools, opponents on ADP
order (B1 measured all seven as ESPN-anchored), our seat taking `recommend`'s top row.

**Mechanically clean, twice:** 128 `mark_taken` / `undo_taken` / re-mark round-trips, **zero
undo failures**, clock correct throughout, `draft_complete` true, all nine starting slots
filled, D/ST at R14, K at R15, QB at R16.

| | before the fixes | after |
|---|---|---|
| D/ST or K recommended before round 14 | **20** | 4, none of them the top row |
| first D/ST taken | **round 7** | round 14 |
| first K taken | **round 9** | round 15 |
| starting slots left empty | 0 (but 2 D/ST rostered) | 0 |

### The one thing still wrong, and it is not fixed

The resulting roster is **10 WR, 2 RB, 1 TE, 1 QB, 1 DEF, 1 K**. On the earlier data pull it
was 6 TE. Neither is a real roster.

`recommend` with slack to spare is pure best-available by our VORP, with no notion of
positional balance. Whichever position our board rates above where this room drafts it gets
hoovered — TE last week, WR this week. **Two running backs in a league that starts two plus a
flex is one hamstring from a dead season.**

This is deliberately **not** patched, for a reason worth keeping: taking receivers in a
league that pays WR 0.5 a catch and RB nothing *is the documented edge*. The failure is
roster construction, not valuation, and STATE already records the whole-position
TE/QB-vs-market gap as unresolved with an explicit *do not act on it*. Capping a position
would be picking a side in that argument on no evidence, days out.

**Draft-night rule, until there is a real fix:** `recommend` returns five rows — read all
five, not the first. When you already hold three startable bodies at a position, take the
best row that is not that position. Use `best_available(position="RB")` to see what the run
on your thin position actually costs. The tool ranks value; you own the roster shape.

The right fix later is marginal value **against my own roster** rather than against the
league — a fourth WR displaces nobody in my lineup, so his value is injury insurance, not
his VORP. That is a feature, not a bug fix.

---

## Draft-night state of play

| | |
|---|---|
| local cockpit | `scripts\draft-day.cmd` → League B, correct |
| pinned image | `sha256:d3cd…be570` = main @ `39a13f3` — **predates every fix above** |
| rollback | tag `pre-draft-known-good` (main @ `6a03bb4`), digest recorded in README |
| cluster | **serving League A — see the STOP section** |
| public MCP | endpoint proven up to the auth boundary; the join needs one human OAuth login |
| data cache | refreshed 2026-08-25: 3302 League B players, 5 nflverse sources, board builds from disk |

**The pinned image is the safe option, not the current one.** It is a known-good board on
which the top D/ST still ranks 33rd. To ship the fixes, rebuild, re-pin, and record the new
digest in README *beside* the old one — never over it.

Still needing a human, in priority order:

1. **Restart the cluster container on League B**, and verify with the `grep` above.
2. **Connect Claude to `https://mcp-audible.havenhomelab.org`, log in, ask `draft_status`.**
   Nine starting slots and `my_slot 8` means the whole path is good. Eleven slots and
   `SUPER_FLEX` means item 1 is still live. This is the only untested join.
3. **Decide: pinned image, or rebuild on the fixes.** Both defensible; the fixes are large
   and tested, the pinned image is unexercised in a container.
4. **`audible refresh-data` the day before**, and confirm the volume maps to
   `/app/data/cache` in the container.
5. **Drive the cockpit once on the actual phone.** It is verified under simulated touch in a
   headless browser, not under a real thumb on real Safari.

---

## The board builds offline — the property that matters on draft night

Every board input used to be a third-party URL fetched fresh on every process start, because
nflreadpy caches **in memory only**. On 2026-08-17 one of those URLs started returning a 404
page and the board stopped building entirely.

Now: **the network is an update mechanism, not a dependency.**

- `FrameCache` (`adapters/cache.py`) — parquet on disk plus a manifest of source, fetch time,
  checksum, rows. **Deliberately no TTL.** A time-to-live expires on its own schedule, which on
  draft night means the one restart that matters is the one that decides to go to the network.
  Present means used.
- Every nflverse loader routes through it. A fetch that fails with a cached copy present is not
  an error — the copy is the answer. A fetch that fails with **no** cache still raises, because
  silence is the one unacceptable outcome.
- Sleeper projections are cached too. They were not, and they *are* the projections — no amount
  of nflverse caching could have produced an offline board without them. The players catalog
  keeps its TTL for freshness but serves stale rather than failing.
- **`audible refresh-data`** is the one command that is supposed to need the network. It
  refreshes by building each league's board, so the cache holds exactly the sources `serve`
  will ask for at the seasons it will ask for them.
- `/healthz` reports source count, age, and whether inputs came from disk or network.

**Verified with outbound sockets blocked** (`getaddrinfo`, `connect`, `connect_ex`):

```
espn_davis_drive  3300 players  DEF=32 K=157 QB=355 RB=744 TE=649 WR=1363
sleeper_boyfun    7621 players  + DB=1778 DL=1439 LB=1136
#1 Jahmyr Gibbs in both — identical to the online build
serve: ok:true, data.origin "disk", sync_status "failing"
```

**Run `audible refresh-data` the day before the freeze.** Last run 2026-08-25. The volume must map to
`/app/data/cache` in the container.

---

## C1/C2 — draft quality, and whether it decides anything

`audible draft-quality espn_davis_drive`. All five seasons (no ADP needed).

**C1 — mean draft rank across 2021–25 (1 = best draft that season):**

| seat | mean | sd | best | worst | mean finish |
|---|---|---|---|---|---|
| WCW | 2.20 | 0.84 | 1 | 3 | 2.60 |
| Ryan | 3.00 | 3.08 | 1 | 8 | 3.60 |
| BTD | 3.40 | 1.67 | 2 | 6 | 4.20 |
| FAT | 5.00 | 1.87 | 3 | 7 | 5.40 |
| BUTT | 5.00 | 2.24 | 2 | 8 | 4.00 |
| PM | 5.20 | 2.49 | 1 | 7 | 7.00 |
| Cnk | 5.80 | 1.92 | 3 | 8 | 4.80 |
| JEFF | 6.40 | 1.52 | 5 | 8 | 4.40 |

One seat drafts consistently well (**WCW**, never worse than 3rd). One is pure variance
(**Ryan**, best *and* worst in five years). The rest reshuffle. **BUTT is Eric** — mean draft
rank 5.00, mean finish 4.00.

**C2 — does drafting predict finishing? Not resolvably, at this sample size.**

Per-season rho(draft rank, finish): −0.167, +0.262, +0.214, **+0.976**, +0.571.

| unit | rho | 95% CI |
|---|---|---|
| draft → finish | +0.371 | [−0.160, +0.903] |
| draft → points for | +0.414 | [−0.212, +1.040] |

**Both intervals cross zero.** The pooled n=40 figure looks better powered than it is: within
a season the eight draft ranks are a permutation and so are the finishes, so seats are not
independent and pooling counts one season's evidence eight times. Seasons are independent —
that leaves **n=5**, and the per-season values run from −0.17 to +0.98 with one season
carrying the mean.

So this neither establishes that draft edge decides seasons here nor that it doesn't. Five
seasons of an eight-team league is all the data that exists; **B3's corpus widening is the
only way to sharpen it, and it can run after the draft.**

The draft tracks **points** more closely than **standings**. A better draft scores more;
converting that into wins runs through a schedule nobody controls.

*Caveat stated, not solved: drafted-roster points ignore waivers, trades and start/sit. It
measures the draft, not the season.*

---

## B-next — the scoring edge IS real, and B1's "no edge" was half the story

`audible rank-check espn_davis_drive`. B1's conclusion (below) still holds for whole
archetypes. But the rank comparison that supported it was **top-24 only**, and that is the one
tier where agreement is guaranteed for reasons unrelated to scoring — elite receivers are
elite in every format.

Across ranks 25–200 the boards diverge sharply:

| tier | n | mean | median | mean&#124;d&#124; | moved |
|---|---|---|---|---|---|
| 1–24 | 24 | −1.4 | −0.5 | 2.5 | 1 |
| 25–60 | 36 | −4.1 | −9.0 | 14.9 | 25 |
| 61–120 | 60 | +0.6 | −5.5 | 22.8 | 50 |
| 121–200 | 34 | +4.2 | 0.0 | 11.3 | 13 |

**Divergence alone proves nothing** — two boards can disagree for reasons unrelated to
receptions. So the hypothesis is tested directly: Spearman(receptions, rank delta) **within
position**.

| pos | 1–24 | 25–60 | 61–120 | predicted sign |
|---|---|---|---|---|
| WR | +0.90 | +0.70 | +0.58 | **+** (paid 0.5/catch) |
| RB | −0.53 | −0.06 | −0.62 | **−** (paid 0.0/catch) |
| TE | — | — | −0.14 | + (weak/contrary) |

Both major signs came out as predicted. **The edge is real, it is in rounds 3–10, and it is
within position rather than across it:**

- Among **WRs at a similar ESPN rank** — take the high-reception possession receiver over the
  low-volume deep threat.
- Among **RBs** — fade the pass-catching back, prefer the pure rusher.

**Do not act on the whole-position moves.** QB and TE rise as blocks on our board; that is
VORP-versus-market structure, not receptions, and this gate establishes nothing about which
side is right. The CLI verdict says so explicitly.

**Method note worth keeping:** the first cut averaged the within-position correlations, which
is wrong — the scoring predicts *opposite* signs by position, so a real WR effect and a real
RB effect cancelled and the verdict read "not reception-driven". Averaging across groups with
opposing predicted signs will always do this.

---

## B1 — opponent anchoring: settled (whole archetypes only)

`audible anchoring espn_davis_drive`. 384 picks over 2023–25, 79.9% usable.

| seat | disc | sp(STD) | sp(PPR) | mad(STD) | mad(PPR) | edge | ±1.96se | reads like |
|---|---|---|---|---|---|---|---|---|
| PM | 12 | +0.914 | +0.780 | 14.1 | 22.9 | +26.3 | 20.1 | espn |
| FAT | 14 | +0.853 | +0.728 | 19.6 | 27.9 | +24.4 | 11.2 | espn |
| WCW | 13 | +0.806 | +0.752 | 23.3 | 29.4 | +18.1 | 16.3 | espn |
| Cnk | 13 | +0.884 | +0.792 | 15.4 | 19.8 | +12.7 | 10.7 | espn |
| JEFF | 16 | +0.847 | +0.723 | 18.4 | 22.6 | +8.2 | 15.5 | unclassified |
| Ryan | 15 | +0.858 | +0.826 | 19.9 | 23.0 | +7.5 | 11.4 | unclassified |
| BTD | 17 | +0.778 | +0.769 | 20.4 | 23.9 | +6.1 | 10.4 | unclassified |

`edge` = mean(|PPR rank − pick|) − mean(|STANDARD rank − pick|) over picks where the boards
disagree by ≥10 ranks. Positive ⇒ the seat tracks ESPN's board.

**Verdict: no seat is PPR-anchored. All 7 of 7 lean toward ESPN's board (sign test
p = 0.016).** Individually most seats are underpowered at ~13 discriminating picks; the
unanimity is not, and that is the level the finding is stated at.

**What this means on draft night — as amended by B-next above.** No opponent is on a generic
PPR board, so there is no *whole-archetype* steal: don't plan to hoover up Henry-types late,
this room is not systematically undervaluing them.

But because all seven read ESPN's ordering, and our board demonstrably departs from that
ordering on reception grounds inside WR and RB in rounds 3–10, the **within-tier** edge is
live. B1 rules out the crude version of the exploit; it does not rule out the real one.

**Two defects this found, both fixed:**

1. **ESPN's rank tail is a placeholder, not an ordering.** Only ~155 players per season hold a
   STANDARD rank ≤200 and ~280 hold one ≤400; ~800 more carry values running to **2687**. A
   player can sit at STANDARD 57 / PPR 2554 — that is one board declining to rank him, not the
   boards disagreeing. Left in, a few of these dominated every average (mean divergence 85.2
   vs median 10.0; standard errors of 250+ where the effects are ~20). **`RANK_HORIZON = 200`**
   now excludes them and the excluded count is reported. This is another instance of the B6
   silent-empty class: a field that looks like data and is not.
2. **A zero standard error read as no signal instead of a perfect one.** Every discriminating
   pick pointing the same way by the same margin is the strongest possible result, and the
   guard rejected exactly those.

---

## The `image` workflow failure — resolved

It was the **smoke test**, not the build. Steps 1–6 were always green; step 7 ran the full
455s of its 90×5s health loop because `/healthz` never went green — the board could not build
inside the container after the DynastyProcess 404. PR #9's smoke test passed in **17 seconds**
before that URL broke; PR #10's never got there after.

The smoke test now tests the **image**: the container must start, answer `/healthz` with the
contract's keys, and render the index. Board readiness from a cold cache is **reported, not
gating** — it is a live-network question, and a gate that reddens during someone else's outage
is one you learn to ignore. Now green in 18s. The board path is covered deterministically and
offline in `tests/test_datacache.py` instead.

---

## ESPN — verified, do not re-derive

### Auth and transport

- `League(league_id=6012, year=season)` with cookies `espn_s2` and `SWID` (braces kept), read
  from `.env`. Read-only; nothing writes to ESPN.
- Endpoint: `lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leagues/6012`.
- **The ESPN endpoint is not edge-cached.** Measured: `x-cache: Miss from cloudfront`,
  `cache-control: must-revalidate`, no `age` header. Use a conditional GET with `If-None-Match`
  and **no cache-buster** — a repeat request returns `304` with 0 bytes.
  **Sleeper needs a cache-buster; ESPN does not. Do not generalise either way.**

### Player pool

- `view=kona_player_info` plus an `X-Fantasy-Filter` header.
- **`sortDraftRanks` is mandatory.** Without it the endpoint returns `200` with zero players and
  no error of any kind. An empty pool raises rather than becoming an empty board.
- Pool saturates at **1,026**.

### Translation map

- **RB / WR / TE:** exact via statIds `{3, 4, 20, 19, 24, 25, 26, 42, 43, 44, 53, 72}`.
- **QB:** passing yards ride **`statId 8`** — ESPN's bucketed "one point per completed 25 yards".
  `statId 3` (raw yards) is *not a scoring item in this league for any position*. Converting
  buckets back to yards reproduces ESPN exactly through our own `pass_yd = 0.04`
  (25 × 0.04 = 1.0), so no ESPN branch enters the scoring engine.
  Measured: Josh Allen `statId 3 = 3944.73`, `statId 8 = 157` buckets = 3925 yards.
- **K and D/ST:** ESPN-native verified, translation **incomplete — flagged, not fixed**:
  - kicker misses are bucketed −1 / −2 / −3 (statIds 200/203, 82, 88) against our flat
    `fgmiss = -1`;
  - D/ST yards-allowed tiers are absent entirely (128/129/130 = +5/+3/+2;
    133/134/135/136 = −3/−5/−6/−7).
  - ~15 pts/season across two positions holding one roster slot each, drafted last in an
    8-team league. Recorded; not worth a config change.

### Reconciliation residual

`statId 63` (offensive fumble recovered for a TD, paid 6.0) is unmapped — our config has no key
for it and the config is not changing. It is the **entire** difference between our recomputation
and ESPN's own `appliedTotal`:

| pos | delta / season |
|---|---|
| QB | −0.233 |
| RB | −0.069 |
| WR | −0.045 |
| TE | −0.022 |

0.06% of a QB season, monotone in fumbles (already penalised via `fum_lost`). Deliberate.

### Fallback populations

Of the 1,026-player pool: **432** scored by us from translated stat lines, **89** K/D-ST handed
to ESPN by design (the flagged gap above), and **505** offensive players taking ESPN's number —
431 project to 0.0 either way, and 74 are return-only specialists scored on return yards this
league does not pay (largest projects 65 pts against a WR replacement level of 182). All three
paths are counted and printed; none can pass for a computed projection.

### Ranks

`playerRankType = "STANDARD"`. Per-season ranks exist 400/400 for 2023–2025 and are **absent for
2021–2022** — sorting by a rank type that isn't there returns arbitrary order silently.

**STANDARD is not a zero-PPR ordering.** ESPN serves four types (STANDARD, PPR, ELIMINATION,
SUPERFLEX); STANDARD matches PPR at the top and diverges only for non-receiving backs
(Derrick Henry STANDARD #10 / PPR #19; Chase, Nacua, Gibbs, McBride, Bowers identical in both).
STANDARD is still the right type for this league — it pays RBs nothing per reception — but
anything treating it as a market baseline for a half-PPR field will be wrong.

### Scoring, confirmed live

0.5/reception for WR/TE, **0.0 for RB** (deliberate, commissioner-confirmed). 48 position-scoped
weights, **zero drift**. The half-PPR flip has landed.

Comparison must read `pointsOverrides` per position, not `points`: ESPN encodes receptions as
base 0.0 with QB/WR/TE overrides while our config says base 0.5 with an RB override. The two
agree everywhere it matters; a base-against-base comparison reports drift across the whole table
where there is none.

### Draft detail

- `view=mDraftDetail` → `draftDetail.{drafted, inProgress, picks}`.
- **Pre-draft returns a full 128-entry placeholder slate with `playerId: -1`** (8 teams ×
  16 rounds). Filter `playerId != -1`; use `drafted` / `inProgress` for real state. A sync that
  counts raw pick records believes the draft finished before it started.
- Pick fields: `playerId`, `teamId`, `roundId`, `roundPickNumber`, `overallPickNumber`.
- `settings.draftSettings.pickOrder` is teamIds in draft-slot order — measured
  `[2, 3, 6, 4, 1, 5, 7, 8]`, which matches the round-1 slate exactly. It is **not** an identity
  map, so it is real commissioner-set data rather than a Sleeper-style placeholder. Type `SNAKE`,
  `orderType: MANUAL`, 90s per selection.
- Eric's team is derived from `ESPN_SWID` against `teams[].owners` — **team id 8**, which is
  **draft slot 8**. No flag required. Match `owners`, not just `primaryOwner`: at least one
  team in this league is co-owned.
- Rounds = **16**, agreeing two ways: `max(roundId)` over the slate, and
  `sum(lineupSlotCounts) − IR`. The sync uses the second, so the clock does not depend on what
  ESPN serves in the slate once a draft is under way.
- **One request per tick.** `mDraftDetail` + `mTeam` + `mSettings` ride one conditional GET, so
  everything — state, picks, seats, rounds, structure — comes out of that single response.
  Reading rounds back through the adapter's standalone helper silently added a second,
  unconditional `mSettings` request on every 5s tick; there is a test pinning this at one.

### Roster structure

`settings.rosterSettings.lineupSlotCounts`, by ESPN lineup-slot id:
`0:QB=1, 2:RB=2, 4:WR=2, 6:TE=1, 23:FLEX=1, 16:D/ST=1, 17:K=1` = **9 starters**, plus
`20:BE=7` and `21:IR=3`. Matches `leagues/espn_davis_drive.toml` exactly.

`verify-scoring espn_davis_drive` checks this live and reports **faithful** as of 2026-08-17.
An ESPN lineup-slot id we do not map, carrying a non-zero count, reports as `slot#<id>` rather
than being skipped — a starting slot with no name is exactly the drift worth being loud about.

---

## Sleeper — verified, do not re-derive

- Projections/stats on `api.sleeper.com` (undocumented, Rotowire); league/roster/players on
  `api.sleeper.app/v1`. Never trust precomputed `pts_*` — recompute from the raw line.
- **`/picks` IS edge-cached** (Cloudflare `s-maxage=30`, measured 57s stale against a 60s pick
  timer). Every poll needs a unique cache-busting param, then an `If-None-Match` for the cheap
  304. Opposite of ESPN — see above.
- `draft_order` is `null` until the draft opens. `slot_to_roster_id` exists pre-draft as the
  identity map `{1:1, …}` and **lies**: the completed 2025 draft shows `{1:4, 2:2, 3:6, …}`.
  Never derive a slot from it. A resolution derived pre-draft is never cached.
- Users and rosters are not 1:1 — 9 users, 10 rosters, two with `owner_id: null`, one co-owner
  owning no roster.
- ADP `999.0` means "undrafted in this market", not a real ADP.

---

## Known breakage being worked around

**nflreadpy 0.1.5 cannot reach DynastyProcess.** It hardcodes
`https://github.com/dynastyprocess/data/raw/master/files/`, and GitHub now answers that path
with a 404 HTML page. Measured 2026-08-17: that URL returns 404 with 305 KB of error page,
while `https://raw.githubusercontent.com/dynastyprocess/data/master/files/…` returns 200 with
the 2.6 MB CSV. 0.1.5 is the latest release — there is nothing to upgrade to.

`adapters/nflverse.py` tries nflreadpy first and falls back to the raw host for the two
affected loaders. Primary-first means it resumes using upstream on its own once fixed;
**delete the workaround block then.** The disk cache above is the real protection — the
fallback still needs the network to cooperate, and on draft night nothing may.

The fallback reads every column as a string on purpose — this is an ID spine, and a
`sleeper_id` inferred as a float becomes `"4034.0"` the moment anything stringifies it, failing
the join silently for every player instead of loudly for none.

**nflreadpy caches in memory only** (`CacheMode.MEMORY`). That is why the disk cache exists;
without it every process start re-downloads and repeated builds earn a `429` from GitHub raw.

---

## Standing decisions

- **`leagues/*.toml` does not change** to chase a translation gap. Flag it here instead.
- **Manual picks are real picks** — numbered, attributed to whoever is on the clock, and they
  advance the clock. Indistinguishable downstream from synced picks, including `_recent_picks`
  and the run window, both of which read `effective_picks()`. Reversing this caused
  "unlimited players join my roster", "undo leaves them there", and "no other team ever
  appears" from a single line.
- **Never invent a draft slot.** Unresolved is an explicit state; `slot = 0` meant "me" and
  silently attributed the whole room to one roster. Both platforms now derive the seat rather
  than taking a flag, and both return `None` with source `unresolved` when they cannot.
- **One poll loop, one `DraftSession`.** Everything platform-shaped lives behind
  `DraftSync.poll(draft_id, want_meta=, slot_locked=) -> DraftUpdate` in `draft/sync.py`.
  `DraftUpdate` uses `None` for "unchanged": a poll that only fetched picks must not blank the
  draft status it never asked about. Sleeper honours the `want_meta` / `slot_locked` hints
  (three endpoints, and `draft_order` is immutable once open); ESPN ignores both, because its
  whole draft is one response and re-resolving costs nothing — which also means a pre-draft
  pick order the commissioner reshuffles gets followed rather than cached.
- **ESPN picks arrive in ESPN's id space; the board is in Sleeper's.** `EspnIdBridge`
  translates via the Sleeper catalog's `espn_id`. An id that will not translate keeps its ESPN
  value rather than being dropped — the pick really happened, so the clock must move and the
  player must count as taken — and those are counted and logged. This becomes an identity map,
  and the class goes away, when `build_board` reads from the platform adapter.
- **Consensus is the projection of record.** The opportunity model lost out-of-sample at every
  position; it rides as a flag overlay, never as a multiplier.
- **`value_metric = "vorp"` for League B**, not scarcity/VONA — VONA edged it in backtest
  (+28 vs +24) but the current implementation has a junk-tail pathology on flat positions that
  produces a QB-dominated board. Tracked; ship on VORP.
- No model calls inside `audible`, ever. No writes to any platform.

---

## Open / next

**Ordered by what breaks the draft, not by what is interesting.**

1. **The cluster is on the wrong league.** Top of this file. Nothing else matters until it
   is restarted and verified.
2. **`recommend` has no notion of roster balance** — see TASK 5 above. Ten receivers and two
   backs. Not patched, and the reason is recorded. The fix is marginal value against my own
   roster.
3. **The public MCP join is untested** and needs one browser login. Two legs proven, the
   middle unproven.
4. **The pinned image predates every fix.** Rebuild-and-re-pin or run known-good; decide
   before the freeze, and record the digest either way.

Lower, and none of it blocks the 30th:

- **The D/ST residual.** The board still lists LAR D/ST as a mild target (+22 on ADP, down
  from +99). Our board says round 10, a 12-team market says round 11 — and an 8-team league
  needing 8 of 32 should want them *later*, not earlier. The remaining gap is that D/ST and
  K preseason projections carry a 14-point spread that is probably not predictive at all.
  Shrinking it is a modelling change with its own evidence bar.
- **`_slim` drops `points` and `value`**, so no MCP tool shows the raw projection or the
  ADP target/fade signal — only ranks. The 30-point RB reception split is invisible on the
  MCP surface even when correct.
- **`SLEEPER_SOURCED_CAVEAT` never reaches the MCP surface** (one caller, `cli.py`), so a
  model querying League B is never told the board is Sleeper stat lines scored through ESPN
  weights.
- **No board-building path runs a drift guard.** `expected_reception_points` is read in
  exactly two places, both in `cli.py`.
- **League A's replacement baseline is still the old one**, with the same D/ST inflation.
  Needs the supply rule described above.
- **P0.3 (browser regression suite in CI)** is still not started. The surface is now
  identified, so this is finally the right order — the thumb-layer contract test in
  `test_server.py` is a placeholder for it, not a substitute.
- **A1 latency** remains unmeasured and optional; manual entry is primary and the runbook
  assumes it.
- **Track B** (B2, B3 corpus widening, B4-B7) all runs after the draft.
