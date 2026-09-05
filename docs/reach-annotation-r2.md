# Reach annotation, R2 — metric pre-registered 2026-09-05, before any number was computed

R1 is on record in `docs/reach-annotation-gate.md` (branch `feat/reach-annotation`): it
pre-registered `delta = value_rank - current_pick`, fired at `delta >= 40`, passed its
sensitivity gate on Burrow, and then **failed its specificity gate at 12 firings against a
ceiling of 8**. Its own diagnosis is the reason this file exists:

> six of twelve are QBs — the rule detects the structure of VORP, not a reach.
> Median(value_rank − consensus_rank): **QB +178**, RB −30, WR −22, TE −32.

That is not a threshold problem and it cannot be tuned away. In a 1-QB league the board
ranks quarterbacks ~178 places below consensus *by construction*, because a QB's points
above his own replacement are small when ten of them start. Comparing that number to a
pick number reports the shape of VORP on every quarterback ever drafted.

## What R2 measures instead, fixed here before the replay is run

```
reach_picks = market_rank(player) - current_pick
```

**Both terms are market terms.** `market_rank` is the player's dense rank within this
league's own ADP market, over the players that market prices. `current_pick` is the overall
pick number he was taken at (replay) or the pick you are on (live). The board's value rank
does not appear in the formula at all, which is precisely what makes the R1 failure
unreachable: a metric with no VORP term cannot report the structure of VORP.

Positive means **taken earlier than the market would have taken him** — which is what the
word "reach" means to a drafter, and the only reading that is the same word in both leagues.

`market_rank`, not raw ADP, because ADP is a pick-number estimate in a market whose team
count may differ from ours; ranking first and comparing ranks to picks keeps one league's
number meaningful in the other's draft.

## The honesty requirement, which is half the feature

A reach number is a claim that the market knew better. That claim is only worth making
where the market carries signal. From `#36`'s leave-one-year-out fit, held-out Spearman of
ADP-implied points against actual points, with the noise floor `1/sqrt(n-1)` from
`docs/pre-registration-repaired-instrument.md`:

| pos | mean held-out ρ | noise floor | verdict |
|---|---|---|---|
| RB | 0.547 | 0.130 | above |
| WR | 0.464 | 0.122 | above |
| TE | 0.253 | 0.229 | **marginal** — clears by 0.024, weak in four folds of five |
| QB | 0.187 | 0.204 | **below** |
| DEF | 0.103 | 0.289 | **below** |
| K | −0.017 | 0.277 | **below** |

QB, K and DEF are below their own noise floor; TE clears it by 0.024 and is treated as
marginal, not usable. Every one of those four positions carries `market_signal` on the wire
next to the number, on every surface. **A confident reach number for a quarterback is the
exact failure R1 recorded, and shipping one unmarked would be reproducing it.**

Note what this does *not* do: it does not suppress the number. R1's own worst pick was a
QB, and hiding the number would hide the pick it was built for. It marks it.

## Gates — as handed over, not restated from memory, and not adjusted after any output

| | gate | fails if |
|---|---|---|
| G1 | a mutation letting reach enter the sort is caught by a board-order invariant asserting VORP never rises | that invariant does not fire, or others also fire |
| G2 | DDAFFL replay: Burrow at overall 57 annotates as a reach of ≥40 picks against that league's market | <40, or the pick does not annotate |
| G3 | across all 128 DDAFFL picks, fewer than 25% flag as a reach at the ≥20-pick threshold | ≥25% |
| G4 | per-league market: `adp_ppr` for Danger Zone, `adp_idp` for BoyFun | one hardcoded market, or either league reading the other's |
| G5 | the reach delta present in `best_available`, `recommend`, `compare` and `player_lookup` over a real FastMCP client | absent from any of the four |

Required failure injections: swap the two leagues' markets → G4 must fire; force every ADP
to a constant → G3 must fire; reorder the board by reach with ranks a clean 1..N → G1 must
fire **and only G1**.

## G3 is weaker than the gate that already failed, and that is recorded here

R1's ceiling was 8 firings in 128 (6.3%) at a ≥40 threshold. G3's is 25% at a ≥20
threshold — a looser threshold judged against a ceiling four times higher, written after
R1's 12/128 was known. Under hard stop 6 a gate is not adjusted after a number is seen, so
**R1's original rule is re-measured alongside G3 and both numbers are reported**, and G3 is
not allowed to launder a result that the stricter gate would have refused. If R2 passes G3
only because G3 is loose, that is the finding.

## Inertness

Display only. The lookup happens at the serving boundary in `state._player`, after the
board is built, ranked and frozen — the pattern `draft/usage.py` established. Nothing under
`value/`, `scoring/`, `providers/` or `draft/board.py` may import `draft/reach.py`.

---

# Result — measured once, 2026-09-05. **G2 FAILS. R2 is not built.**

## Harness validation, before any R2 number is quoted

The replay reproduces R1's recorded result exactly, which is what makes the rest of this
trustworthy:

| | this replay | R1 recorded |
|---|---|---|
| firings at `value_rank - pick >= 40` | **12** / 128 | 12 |
| of which QB | **6** | 6 |
| Burrow's R1 delta | **+52** | +52 |

## G2 — FAIL

**Joe Burrow, DDAFFL pick 57. R2 reach = −3.**

| | |
|---|---|
| raw `adp_half_ppr` | **54.5** |
| market rank | 54 |
| taken at pick | 57 |
| **R2 reach (market − pick)** | **−3** |
| consensus rank | 6 |
| VORP rank | 109 |

He went **2.5 picks after** the market had him. The market ranks either side of him were
Drake Maye at 52.3 and Davante Adams at 55.3. **The DDAFFL draft's worst pick was not a
reach.** It was taken almost exactly on ADP.

R1's "+52" was `vorp_rank(109) − pick(57)`. That is a statement that this board's VORP puts
Burrow 109th, which it does because a quarterback's points above his own replacement are
small when eight of them start. It was never a statement about the pick being early. The
whole motivating example of both R1 and R2 is an artifact of subtracting a pick number from
a VORP rank.

**G2 and G4 cannot both be satisfied.** G2 enshrines the number 40, which only exists under
a VORP metric; G4 requires the metric to read the league's ADP market. Under the market
metric G2's own example scores −3. The gate is not adjusted (hard stop 6) and the metric is
not swapped back to R1's, which already failed its own specificity gate.

## G3 — PASS, and it does not rescue anything

15 of 128 = **11.7%** at the ≥20 threshold, against G3's 25% ceiling.

Reported alongside, as pre-registered above: R1's original stricter rule re-measured at
**12/128 = 9.4% against its 6.3% ceiling — still a FAIL.** G3 passes here only because it is
four times looser than the gate this feature already failed.

## What the firings actually are

| position | firings at ≥20 | ADP→points signal |
|---|---|---|
| K | 8 | below noise floor |
| DEF | 4 | below noise floor |
| TE | 1 | marginal |
| RB | 1 | usable |
| WR | 1 | usable |

**13 of 15 firings are at or below the ADP noise floor.** Honestly marked, the annotation's
entire unmarked signal across a completed 128-pick draft is **two picks — 1.6%**:

```
pick  85  MarShawn Lloyd  [RB]  market 180  reach +95
pick  67  Matthew Golden  [WR]  market 123  reach +56
```

The kicker and defence firings are real and uninteresting: this room drafted its specialists
earlier than the market does. That is a roster-construction observation, and at K and DEF
the market has no signal with which to be right about it.

## The conclusion, stated plainly

Both metrics fail their own defining gate, for one underlying reason. A reach annotation
needs a market that carries signal at the position where the mistake happens. In these
leagues the market is only usable at RB and WR — and the picks that *feel* like reaches are
quarterbacks, kickers and defences, which is exactly where it is not. R1 fired on the
structure of VORP; R2 fires on the structure of specialist ADP. Neither is a reach.

Nothing was wired into the cockpit, so there is nothing to roll back. G1, G4 and G5 were not
run: building the feature to exercise the remaining gates after the defining gate failed is
the tuning this pre-registration exists to prevent.

**What this does not settle.** Measured on DDAFFL only — 8-team, half-PPR, 1-QB. Tonight's
two leagues are 10-team superflex+IDP and 10-team full PPR, and the specialist ADP picture
in a 19-round superflex league is not this one. A future attempt should pre-register against
one of those, and should first answer the question this run raises: is there any position in
either league where the market both carries signal *and* is disagreed with often enough to
be worth a column?
