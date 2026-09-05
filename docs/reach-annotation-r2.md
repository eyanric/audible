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
