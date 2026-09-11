"""S7 -- how many of this session's hits should exist if nothing is real.

    uv run python -m sim.s7_multiplicity > sim/runs/s7-multiplicity.txt

THIS IS AN ACCOUNTING OF TESTS ALREADY RUN, NOT A NEW TEST. It introduces no
threshold, fits nothing, and would produce the same output if every disposition
were reversed. It exists because phases 2 and 3 ran 336 hypothesis tests and
reported each one on its own, and 336 tests at a 5% bar produce hits whether or
not anything is real.

THE NULL RATE IS PER TEST AND IS COMPUTED, NOT ASSUMED, AND THE FIRST VERSION OF
THIS FILE ASSUMED IT. It took P(p <= 0.05) = 2/41 for every test, on the reasoning
that the observed statistic is equally likely to land in any of 41 exchangeable
positions. That is right only when those 41 values are distinct. Out-of-sample
lambda selection puts an atom on exactly 0.000 -- a term that should not be used
selects nothing and scores nothing -- so most floor draws TIE, and with three or
more values tied at the maximum the smallest reachable p is 3/41 = 0.073 and the
test CANNOT return a hit however real the effect is. The adversarial review
measured five of six sampled terms in that regime, where the true null rate is
ZERO rather than 0.0488, and 131 of 336 tests in the superseded hash-floor run had
an effect of exactly 0.000.

So each test now carries its own `null_hit_rate`, enumerated from its own tie
structure by `s7_phase2.null_hit_rate`, and the benchmark is the sum of those. A
test that could never have produced a hit contributes 0 to the expectation and
cannot flatter the accounting in either direction.

THE VARIANCE IS NOT BINOMIAL EITHER. The board p and the four positional p values
inside one record share the same 40 floor draws, so the tests are correlated and a
binomial standard deviation is too small. The overdispersion is estimated from the
per-record hit counts and reported beside the naive figure.

REPLICATION IS THE PART THAT MATTERS. Three leagues share the same weeks, the same
players and the same projections, and differ only in a rulebook. A signal about how
football works should not care which of the three you looked at. A chance hit
should land in one league and not the others, and that is what "hit in >= 2
leagues" counts.

The leagues are NOT independent, so the >=2 count is not converted into a p-value
here. The same player-weeks drive all three, so a real effect and a shared quirk of
the data would both replicate. What the count can do is falsify: a term that hits
in one league and misses in the other two has failed the cheapest test there is.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import s7_phase2 as p2

RUNS = Path(__file__).resolve().parent / "runs"

# The rate a test WITH NO TIES would carry. Kept only as a reference point in the report; the
# benchmark itself is the sum of each test's own enumerated rate.
ALPHA_NO_TIES = 2.0 / (1.0 + p2.FLOOR_DRAWS)


def records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(RUNS.glob("s7-phase[23]-*.jsonl")):
        phase = "phase3" if "phase3" in path.name else "phase2"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            record["_phase"] = phase
            record["_name"] = record.get("signal") or record.get("metric")
            out.append(record)
    return out


def main() -> int:
    rows = records()
    if not rows:
        print("no phase 2 or 3 records on disk")
        return 1
    print("S7 MULTIPLICITY -- an accounting of tests already run")
    print(f"floor draws {p2.FLOOR_DRAWS}; a test with NO TIES carries "
          f"P(p <= 0.05) = 2/{1 + p2.FLOOR_DRAWS} = {ALPHA_NO_TIES:.5f}, but the benchmark "
          "below is the sum of each test's OWN enumerated rate.")
    print()

    tests = 0
    hits: list[tuple[str, str, str, float]] = []
    rates: list[float] = []
    per_record: list[int] = []
    unreachable = 0
    for record in rows:
        candidates: list[tuple[str, float, float]] = []
        if record.get("p_board") is not None:
            candidates.append((
                "board", float(record["p_board"]),
                float(record.get("null_hit_rate_board", ALPHA_NO_TIES)),
            ))
        positions = record.get("p_position") or {}
        by_position = record.get("null_hit_rate_position") or {}
        for where, value in positions.items():
            candidates.append((
                where, float(value), float(by_position.get(where, ALPHA_NO_TIES)),
            ))
        record_hits = 0
        for where, value, rate in candidates:
            tests += 1
            rates.append(rate)
            if rate == 0.0:
                unreachable += 1
            if value <= 0.05:
                hits.append((record["_name"], record["league"], where, value))
                record_hits += 1
        per_record.append(record_hits)

    expected = sum(rates)
    binomial_var = sum(rate * (1 - rate) for rate in rates)
    naive_sd = binomial_var ** 0.5
    print(f"measurements (term x league) : {len(rows)}")
    print(f"p-values computed            : {tests}")
    print(f"   of which CANNOT return a hit at 0.05, because of ties in their own floor: "
          f"{unreachable}")
    print(f"hits at p <= 0.05            : {len(hits)}")
    print(f"expected under a pure null   : {expected:.1f}   "
          f"(a flat 2/41 would have said {tests * ALPHA_NO_TIES:.1f})")

    # Overdispersion: the five tests inside a record share 40 floor draws. Estimated as the
    # ratio of the observed variance of per-record hit counts to the binomial variance those
    # records would have if their tests were independent.
    counts = per_record
    mean_count = sum(counts) / len(counts)
    observed_var = sum((c - mean_count) ** 2 for c in counts) / (len(counts) - 1)
    independent_var = binomial_var / len(counts)
    phi = observed_var / independent_var if independent_var > 0 else float("nan")
    sd = naive_sd * (phi ** 0.5 if phi == phi and phi > 0 else 1.0)
    print(f"sd, tests treated as independent : {naive_sd:.1f}")
    print(f"sd, corrected for the shared floor inside a record (phi {phi:.2f}) : {sd:.1f}")
    print(f"excess over the null         : {len(hits) - expected:+.1f}  "
          f"({(len(hits) - expected) / sd:+.2f} sd)")
    print()

    where_hit: dict[tuple[str, str], set[str]] = defaultdict(set)
    for name, league, where, _p in hits:
        where_hit[(name, where)].add(league)
    replicated = {k: v for k, v in where_hit.items() if len(v) >= 2}
    print(f"(term, place) pairs hit in >= 2 leagues : {len(replicated)}")
    for (name, where), leagues in sorted(replicated.items()):
        print(f"   {name} at {where}: {sorted(leagues)}")
        for record in rows:
            if record["_name"] != name:
                continue
            effect = (
                record.get("effect_board") if where == "board"
                else (record.get("per_position") or {}).get(where)
            )
            p_value = (
                record.get("p_board") if where == "board"
                else (record.get("p_position") or {}).get(where)
            )
            print(f"      {record['league']:18s} effect "
                  f"{(effect if effect is not None else float('nan')):+7.4f}  "
                  f"p {(p_value if p_value is not None else float('nan')):.4f}  "
                  f"verdict {record.get('verdict')}")
    print(f"(term, place) pairs hit in exactly 1 league : "
          f"{sum(1 for v in where_hit.values() if len(v) == 1)}")
    print()

    verdicts: dict[str, list[str]] = defaultdict(list)
    for record in rows:
        if record.get("verdict") == "RESOLVES":
            verdicts[record["_name"]].append(record["league"])
    print(f"verdict RESOLVES: {sum(len(v) for v in verdicts.values())} across "
          f"{len(verdicts)} distinct terms")
    for name, leagues in sorted(verdicts.items()):
        print(f"   {name:20s} {sorted(leagues)}")
    print(f"terms resolving in >= 2 leagues: "
          f"{sum(1 for v in verdicts.values() if len(v) >= 2)}")
    print()

    effects = [r["effect_board"] for r in rows if r.get("effect_board") is not None]
    print("board-wide selected effects, all measurements:")
    print(f"   n {len(effects)}   exactly 0.0 (selection chose lambda 0 in every fold): "
          f"{sum(1 for e in effects if e == 0.0)}")
    print(f"   > 0: {sum(1 for e in effects if e > 0)}   < 0: {sum(1 for e in effects if e < 0)}")
    print(f"   mean {statistics.mean(effects):+.4f}   median "
          f"{statistics.median(effects):+.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
