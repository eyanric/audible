"""S7 -- how many of this session's hits should exist if nothing is real.

    uv run python -m sim.s7_multiplicity > sim/runs/s7-multiplicity.txt

THIS IS AN ACCOUNTING OF TESTS ALREADY RUN, NOT A NEW TEST. It introduces no
threshold, fits nothing, and would produce the same output if every disposition
were reversed. It exists because phases 2 and 3 ran 336 hypothesis tests and
reported each one on its own, and 336 tests at a 5% bar produce hits whether or
not anything is real.

THE NULL RATE IS EXACT, NOT ASSUMED. A reference-set p over K salts can only take
the values (1+j)/(1+K) for j in 0..K, so with K = 40 the reachable values are
1/41 = 0.0244, 2/41 = 0.0488, 3/41 = 0.0732 and up. Exactly two of them sit at or
under 0.05. Under the null a salt draw and the signal are exchangeable, so the
observed statistic is equally likely to land in any of the 41 positions, and
P(p <= 0.05) = 2/41 = 0.04878 per test. That is a property of the test's
construction and needs no distributional assumption about football.

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

# The reachable p grid is k/(1+FLOOR_DRAWS); exactly two of its values are <= 0.05.
ALPHA = 2.0 / (1.0 + p2.FLOOR_DRAWS)


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
    print(f"floor draws {p2.FLOOR_DRAWS}, reachable p grid k/{1 + p2.FLOOR_DRAWS}, "
          f"so P(p <= 0.05) = 2/{1 + p2.FLOOR_DRAWS} = {ALPHA:.5f} exactly")
    print()

    tests = 0
    hits: list[tuple[str, str, str, float]] = []
    for record in rows:
        candidates: list[tuple[str, float]] = []
        if record.get("p_board") is not None:
            candidates.append(("board", float(record["p_board"])))
        for where, value in (record.get("p_position") or {}).items():
            candidates.append((where, float(value)))
        for where, value in candidates:
            tests += 1
            if value <= 0.05:
                hits.append((record["_name"], record["league"], where, value))

    expected = tests * ALPHA
    sd = (tests * ALPHA * (1 - ALPHA)) ** 0.5
    print(f"measurements (term x league) : {len(rows)}")
    print(f"p-values computed            : {tests}")
    print(f"hits at p <= 0.05            : {len(hits)}")
    print(f"expected under a pure null   : {expected:.1f}  sd {sd:.1f}")
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
