# B8 — a market is a config plus an ADP source

Branch `feat/sim-markets`. Nothing merged. Artifacts: `b8-ffc.json`, `b8-mfl8.json`,
`b8-mfl12.json`, plus `b8-counterfactual-{asis,b1room}.json`.

Gates: `sim/test_g_b8.py`, 54 checks; full sim suite 286 green; `uv run pytest`,
`uv run ruff check .`, `uv run pyright` all clean.

**Two of the three runs exit non-zero, on purpose, and neither failure is fixed.** They are the
result.

---

## What the session set out to do, and what it actually found

The plan was: make the market declarative, add MFL as a second market, and compare. The
abstraction works and the comparison ran. But the first thing the second market revealed was a
defect in the harness rather than a fact about the transform:

> **MFL's eight-team board changes the opponent model, and every earlier session's room
> validation was an FFC fact wearing a general one's clothes.**

`room.fit_room` puts a position on the SCHEDULE clock when the room drafts more of it than the
board's top 128 supplies, and `room._best` then removes every scheduled position from the board
the bots pick off. B1 validated a room whose scheduled set is `{DEF, K}`. Measured:

```
supply ratio (drafted / available in the top 128), cut at 1.0
                 K       DEF     WR      RB      TE      QB     scheduled
ffc_12_std      inf     3.818   0.930   0.877   0.867   0.783   {DEF, K}
mfl_12_std     3.727    2.211   0.988   0.939   0.812   0.722   {DEF, K}
mfl_8_std      1.414    1.105   1.111   1.047   0.776   0.657   {DEF, K, RB, WR}
```

On MFL's eight-team board RB and WR cross the cut, so the bots **cannot draft a running back or
a receiver off the board at all** and fall through to taking three quarterbacks each in a
one-QB league. Everything still ran. Every arm produced a number, every interval computed, the
artifact looked ordinary.

`SUPPLY_RATIO_CUT`'s own comment argues that 1.0 "is a meaning rather than a threshold" on the
strength of a factor of 2.25 of clearance. That clearance is an FFC measurement. At 1.047 the
cut is doing real work.

## The result I nearly reported, and why it is withdrawn

The first draft of this document led with a sign reversal: `transform - points_greedy` at
+122.3 in FFC, +81.7 in MFL 12-team, and **−97.1 [−161.9, −32.2]** in MFL 8-team — the market
that matches both real leagues on team count. It read as "the transform's value was conditional
on a market nobody declared."

**That was wrong, and the counterfactual says by how much.** `sim/b8_room_counterfactual.py`
runs the identical MFL 8-team config twice, changing only the scheduled set:

```
five seasons, twenty seeds, everything else identical
                        as shipped                 room forced to B1's {DEF, K}
transform - points   -83.7 [-132.0, -35.5]        +87.9 [ -13.0, +188.8]
transform - adp      -46.9 [-105.8, +12.0]        -49.0 [-168.3,  +70.2]
real - adp           -31.7 [-164.5, +101.2]       +15.1 [-107.8, +137.9]
real - shuffle       +93.9 [  -4.9, +192.7]       +68.6 [ -40.6, +177.9]
```

The room accounts for **−171.6** of `transform - points` and **+2.2** of `transform - adp`.
With a valid room the eight-team market agrees in sign with the other two. **The reversal was
the opponent model, not the market.** That claim is withdrawn in full.

What survives is the more interesting half: `transform - adp` is untouched by the room
(−46.9 against −49.0) and negative in all three markets. The finding B4, B5 and B7 kept
producing — the transform does not beat the market's own ordering — now also survives a change
of market and a change of opponent model.

## The three runs, side by side

Reported because they were run, with the caveat that **only the FFC column comes from a room
that passes validation.**

```
                                  FFC 12-team          MFL 8-team          MFL 12-team
                                    (gates pass)      (G7 FAILED)         (G6a FAILED)
real - shuffle   (leak detector)  +97.3 [+58,+136]  +104.5 [+34,+175]   +89.9 [+14,+166]
transform - adp                   -35.4 [-94, +23]   -51.8 [-97,  -7]   -38.2 [-141,+65]
real - adp                        +17.9 [-16, +52]   -24.3 [-137, +88]  +46.2 [-63,+155]
transform - ffa_baseline          -66.7 [-93, -41]   -27.2 [-83, +29]   -68.8 [-115,-23]
transform - points                +122.3[-67,+311]   -97.1 [-162,-32]   +81.7 [+12,+151]
ceiling - adp                    +300.4 [+140,+461] +354.9 [+169,+541] +410.1 [+202,+618]
```

- **The leak detector holds in all three**, at nearly the same size. A market swap does not
  disturb it, and neither does the broken room.
- **B5's `ffa_baseline` finding survives**: FFA's replacement depth still beats ours by 66.7 in
  FFC and 68.8 in MFL 12-team.
- `b8-mfl12` fails **G6a, the null control**: a bot in seat 6 scores +22.0 [+6.7, +37.4] where
  symmetry demands chance. Its room passes G7, so this is a second and separate problem, and it
  means the twelve-team MFL column cannot be read as a quantity either.

**So the FFC-versus-MFL comparison this session was asked to produce does not exist yet.**
Neither MFL market currently yields a valid room. That is a smaller result than "the transform
reverses", and it is the one the evidence supports.

## What was built

`sim/markets.py` — a `Market` is `(name, league, source, params, provenance)`. `REGISTRY` holds
three. One module-level active market, set once from the run config by `runner.execute` before
preflight.

The global is deliberate: `room.load_board` has forty-odd call sites and `fit_room` calls it
internally, so threading a parameter through all of them would touch far more code for a value
constant over a run. `markets.use()` scopes it for a test.

`b8-ffc.toml` and `b8-mfl8.toml` are identical as parsed except the run name and one
`market =` line — that is G1, and it is checked by comparing the loaded TOML documents rather
than a text slice.

Seams wired: `room.load_board` (dispatch), `room.PRE_DRAFT_SOURCES`, `runner.RunConfig.market`,
`runner.load_config` (unknown market and league/market mismatch both refused in preflight),
`runner.required_inputs` (the market names its own pins, and only its own),
`runner.gate_failures` (**new G7, room fidelity**), and the artifact's `market` block.

**`config_hash` was widened by four fields.** `market` had to go in or `--resume` would append
one market's units to another's. `projection`, `historical_deltas` and `score_kickers` were
*already* missing — so before B8 a B4 walkforward run and a B5 FFA run of the same name could
share a checkpoint and report the mixture as one config.

**Deliberately not generalised:** the `ffc%04d` draftable-id prefix stays `ffc` for every
market. It means "board row N", it is written into every committed artifact and checkpoint, and
renaming it would invalidate every recorded run while changing no behaviour. Now named as
`room.DRAFTABLE_PREFIX`.

## MFL, and the defects it nearly shipped with

`sim/mfl.py` pins `TYPE=adp` plus the player catalogue per season, `PERIOD=AUG15`,
`IS_KEEPER=N`, `IS_MOCK=0`; fifteen files under `data/sim-cache/mfl/`. Measured before
building: `FCOUNT` is a real filter; the year path is genuinely vintage; `IS_KEEPER=N` matters
(262 drafts against 287); `PERIOD=START` is a different population, not a later window.

**MFL's `timestamp` is not provenance** — it is stamped when the response is generated and
reads as today on a 2019 request. MFL publishes no window end, so `Market.asof` returns the
window's *start*, a lower bound. The pre-draft property is carried by content instead.

Four defects found, three of them by adversarial review after I had already written the report:

**1. The board joined at 7 of 180 keys and the run completed anyway.** MFL writes
`"McCaffrey, Christian"`; everything else here writes `"Christian McCaffrey"`, and
`normalize` does not reorder tokens. Separately MFL writes `GBP`/`JAC`/`KCC`/`LVR`/`NEP`/
`NOS`/`SFO`/`TBB` where nflverse writes `GB`/`JAX`/`KC`/`LV`/`NE`/`NO`/`SF`/`TB`. Unresolved
rows take the **rookie path** and arrive with a plausible-looking draft-capital prior. Fixed at
the adapter; `test_i1` restores the defect and requires the join gate to collapse below 10%.

```
resolved, top-128 skill rows, five seasons
  FFC 12-team   628/629    MFL 8-team  572/573  (was 0 before the fix)   MFL 12-team 608/610
```

**2. `MflParams.slug()` dropped `is_keeper` and `is_mock`**, contradicting its own docstring.
`fetch` skips a request when the file exists, so a keeper market would have silently adopted
the redraft pin and measured a redraft-vs-keeper difference of exactly 0.0 — while `meta()`
reported `is_keeper: Y` over data fetched with `N`. The pins were renamed to the complete slug.
`test_i6` now varies **every** parameter; the old version proved it for `fcount` alone, which
is exactly why it missed these two.

**3. `Market.asof` defaulted an unrecognised `PERIOD` to 15 August**, so `PERIOD=START` — a
partly in-season population — would have been stamped mid-August and walked through
`assert_pre_draft`. It now raises. The gate that previously *asserted the fallback as correct*
now asserts the refusal.

**4. `ffa.py` and `projection.py` stamped the FFC filename as board provenance on every run**,
so `projection.assert_pre_draft` compared a literal the code had just written against a prefix
the code also owned — true by construction and blind to the file actually read. Both now derive
it from the active market.

Also fixed: a retroactive-rename miss (`Robby Anderson` → `Robbie Chosen`) that was
**asymmetric across markets** — FFC's 2021 board carries the renamed form and resolved, MFL's
carries the contemporaneous one and did not, at board rank 99 for 85.5 season points booked as
zero. That biased exactly the comparison this session exists to run. FFC never writes the old
spelling, so no previously committed FFC number moves.

### What MFL is, and is not

```
top-128 supply, five-season mean, against what the real 6012 drafts took
  real 6012     QB:13.0 RB:40.0 WR:48.0 TE:10.4 K: 8.2 DEF: 8.4
  MFL  8-team   QB:19.8 RB:38.2 WR:43.2 TE:13.4 K: 5.8 DEF: 7.6   deviation 19.6
  MFL 12-team   QB:18.0 RB:42.6 WR:48.6 TE:12.8 K: 2.2 DEF: 3.8   deviation 21.2
  FFC 12-team   QB:16.6 RB:45.6 WR:51.6 TE:12.0 K: 0.0 DEF: 2.2   deviation 28.8
```

MFL's boards are closer to the real drafts' shape, and cover the real drafts better —
`fit_room` joins 640/640 real picks under MFL 12-team and 634/640 under MFL 8-team against
**622/640 under FFC**. FFC's board carries zero kickers where the real drafts take 8.2 a season.

That is also precisely why MFL 8-team breaks the room: a board whose shape matches the real
drafts leaves less surplus, which pushes RB and WR over a supply cut calibrated on a board with
more of them. The two facts are the same fact.

Limitations, none filtered away: MFL drafters self-select onto a dynasty-oriented host; the
eight-team pool over-drafts quarterbacks (19.8 against 13.0), most likely superflex
contamination `FCOUNT` does not exclude; the raw 2024 board carries IDP rows (DL 5, LB 3, DB 4
in the top 128), dropped at the adapter because an eight-team league with no IDP slot cannot
draft a linebacker; 2025's eight-team sample is thin (124 drafts against 214–267 for 2021–24,
thinnest top-128 row seen in 7 drafts); and 0–7 rows a season carry no team at all (unsigned
players), which `seat.py` maps to `XX` and the bye logic then treats as never on bye.

---

## Task 4 — probes. Nothing built.

**DynastyProcess `db_fpecr` — strongest provenance, one disqualifying confound.**
`db_fpecr.csv` is **404**; `db_fpecr.parquet` is live (38.8 MB, 1,830,022 rows, 24 cols). It
carries `scrape_date` spanning **2019-12-27 → 2026-09-04 at a weekly cadence** — a genuinely
dated snapshot, *better provenance than MFL*, which publishes no window at all. All five
seasons have a mid-August scrape (2021-08-13, 2022-08-19, 2023-08-17, 2024-08-16, 2025-08-15),
each ~520 rows of `page_type = redraft-overall`.

But `fp_page` for those rows is **`/nfl/rankings/ppr-cheatsheets.php`** — PPR only. In a league
paying 0 per reception that repeats **exactly the confound that made B5's `ffa_vor` unusable**.
It is also **ECR, not ADP**: what pundits said, not what drafters did — a different quantity,
not a second sample of the same one. Its top 128 holds no kickers or defences.
*Verdict: worth building only as an explicitly-labelled ECR arm, never as an ADP market.*

**ESPN ranks.** Already pinned as `espn_ranks_6012_{2023,2024,2025}.json`. **Three seasons, not
five**, resolving from the live cockpit root rather than sim's, and they are league-6012 ranks
rather than ADP — already load-bearing inside `room.espn_identity()`.
*Verdict: not a market. Too few seasons to cluster on, and the same league rather than a second
one.*

**NFFC.** Reachable. The page drives an XHR to `/adp.data.php` returning **an HTML table
fragment, not JSON**, defaulting to baseball. Team-count options are **10, 12, 14 — there is no
8**, so it cannot answer this session's question. No year or season selector: current season
only, no vintage. High-stakes contest population.
*Verdict: no.*

**FFPC.** `https://myffpc.com/adp/` is **404**, as are two other obvious paths, and the home
page exposes no ADP link. *Verdict: UNRESOLVED — reported as not found rather than worked
around.*

**`ffscrapr`.** Alive but last pushed **2024-11-01**, CRAN 1.4.8 from **2023-02-12**. An **R**
package; audible is Python. Its MFL support wraps `export?TYPE=...` — the same endpoint
`sim/mfl.py` already calls directly. *Verdict: no.*

---

## What this does not say

- It does not say the transform is good or bad in an eight-team league. The one eight-team
  market available produces an invalid room, and the counterfactual that repairs the room is
  not a market that exists.
- It does not identify team count as the cause of anything. MFL 8 against MFL 12 holds the
  source fixed and is the cleanest contrast available, and **both** of its arms are gated red.
- Five seasons remains five. Every interval here has four degrees of freedom.
- The G7 gate is new and has only ever been exercised on markets added this session. It fires
  on `mfl_8_std` and is silent on the other two; that is one true positive, not a track record.
- `sim/test_g_b8.py`'s vintage gate reads `sim/data/ffa/*.csv`, which is gitignored by design.
  On a fresh clone without the FFA drop it **skips**, and a gate that skips is a gate that does
  not exist. Stated rather than worked around.

## Reproducing this

The MFL pins are not committed — `data/sim-cache/` is gitignored for the same reason
`data/cache/` and the FFA drop are. `uv run python -m sim.mfl` fetches every pin every declared
MFL market needs (15 files); `--check` reports what is missing and fetches nothing. It refuses
to overwrite an existing pin without `--force`, because silently refreshing a pinned response
turns a replay into a new experiment.

```
uv run python -m sim.mfl --check
uv run --extra nflverse python -m sim run --config sim/configs/b8-ffc.toml
uv run --extra nflverse python -m sim run --config sim/configs/b8-mfl8.toml     # exits 1, G7
uv run --extra nflverse python -m sim run --config sim/configs/b8-mfl12.toml    # exits 1, G6a
uv run --extra nflverse python -m sim.b8_room_counterfactual
uv run --extra nflverse python -m pytest sim/test_g_b8.py -m slow
```

## What the next session should do first

Not run more markets. Parameterise `sim/test_g_room.py`'s fixture over `markets.REGISTRY` and
give `python -m sim room` and `sim.inv_run` a `--market` flag. B1's validation is the only thing
that says a measurement means anything, and right now it can only be pointed at one market.
