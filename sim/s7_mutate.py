"""G14 for the S7 code: break it on purpose and check the gates notice.

    uv run python -m sim.s7_mutate           # the whole sweep
    uv run python -m sim.s7_mutate --list    # names only, no edits

WHY THIS EXISTS. A gate that cannot fail is worse than no gate, because it reads as coverage.
This project has shipped four inert checks, and `audible#91`'s review found that session's own
new gate vacuous against its own mutation -- the second time the inert thing was the fix for a
review finding. The phase-1 review then named SEVEN vacuous gates in `sim/test_g_s7.py` as first
written. So each mutation below names the gate expected to kill it, and a mutation that survives
is either a hole or an EQUIVALENT MUTANT that has to be argued for in `expected_survivor`.

HOW IT AVOIDS THE TWO TRAPS THIS PROJECT ALREADY FELL INTO:

  * NO EXTRA `-q`. `pyproject.toml` already sets `-q` in addopts; a second one collapses the
    output to a bare count and drops the `FAILED` lines, and `ffa_scrape/mutate.py` reported
    "every gate killed" against a denominator of zero because of it. `-p no:cacheprovider` and
    an explicit `-rf` are used instead.
  * A RED RUN THAT NAMES NO FAILURES IS AN ERROR, not a kill. If pytest exits non-zero without
    naming a failing test the mutation probably broke collection, which proves nothing about the
    gates.

IT NEVER LEAVES A FILE MUTATED. Every mutation is applied, run, and reverted inside a
try/finally, and the original text is re-read from disk and compared at the end. Do not start a
long run while this is in flight: rule 4 of the handoff's durability section, and this module
edits `sim/s7_weekly.py` in place.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "sim" / "s7_weekly.py"
GATES = "sim/test_g_s7.py"


@dataclass(frozen=True, slots=True)
class Mutation:
    label: str
    old: str
    new: str
    kills: str  # the gate expected to fail, by name fragment
    expected_survivor: str = ""  # non-empty means this mutation SHOULD survive, and why


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "2015 weighted is no longer excluded",
        "USABLE_WEIGHTED_FROM = 2016",
        "USABLE_WEIGHTED_FROM = 2015",
        "test_2015_weighted_is_excluded_by_CHOICE_and_the_files_are_there",
    ),
    Mutation(
        "the pinned-outcome filter does nothing",
        "        if require_actuals and season not in pinned:\n            continue",
        "        if False:\n            continue",
        "test_the_actuals_requirement_drops_exactly_the_unpinned_seasons",
    ),
    Mutation(
        "the pinned window goes back to a hardcoded literal",
        "    seasons: set[int] = set()",
        "    return tuple(range(2019, 2026))\n    seasons: set[int] = set()",
        "",
        "EQUIVALENT TODAY BY DESIGN. The literal and the directory currently agree -- that is "
        "exactly what the gates measure and they cannot distinguish two equal answers. The "
        "mutation becomes visible the moment a new season is pinned, which is the failure it "
        "was written against; nothing in a green checkout can see it.",
    ),
    Mutation(
        "vorp collapses to points, so the two scales become one",
        '    if scale == "vorp":\n        return rank.vorp_values(points, position, league_key)',
        '    if scale == "vorp":\n        return dict(points)',
        "test_the_two_scales_are_not_the_same_board",
    ),
    Mutation(
        "an unknown scale silently falls back to points",
        '    raise ValueError(f"unknown scale {scale!r}; expected one of {SCALES}")',
        "    return dict(points)",
        "test_an_unknown_scale_is_refused_rather_than_defaulted",
    ),
    Mutation(
        "a player with no realised row is kept in the pool",
        "    scoreable = [pid for pid in board if pid in realised]",
        "    scoreable = list(board)",
        "test_a_player_with_no_realised_row_is_dropped_not_scored_zero",
    ),
    Mutation(
        "return yards stop being paid, as they were before the review",
        "        pts += RETURN_YARD_POINTS * (",
        "        pts += 0.0 * (",
        "test_the_weekly_and_seasonal_outcomes_use_the_same_rulebook",
    ),
    Mutation(
        "fumble-recovery touchdowns stop being paid",
        '        pts += FUMBLE_RECOVERY_TD_POINTS * float(row.get("fumble_recovery_tds") or 0.0)',
        '        pts += 0.0 * float(row.get("fumble_recovery_tds") or 0.0)',
        "test_the_weekly_and_seasonal_outcomes_use_the_same_rulebook",
    ),
    Mutation(
        "the board position map stops overriding the nflverse one",
        "        merged = self.position if position is None else {**self.position, **position}",
        "        merged = self.position",
        "test_the_position_override_is_not_inert",
    ),
    Mutation(
        "the positions filter is bypassed",
        "        if pos not in positions:\n            continue",
        "        if pos not in positions | OFFENSIVE | frozenset({'DL', 'LB', 'DB'}):\n"
        "            continue",
        "test_g12_the_positions_filter_is_load_bearing_not_decorative",
    ),
    Mutation(
        "the permutation floor is fed a constant outcome",
        "    outcome = {pid: float(i) for i, pid in enumerate(ids)}",
        "    outcome = dict.fromkeys(ids, 0.0)",
        "",
        "EQUIVALENT, AND THE REASON IS THE PHASE-1 FINDING ITSELF. `rank._realised_order` turns "
        "values into within-pool ranks and breaks ties by id, so a constant outcome still "
        "produces a permutation of 1..n -- just a different one. The metric reads only the two "
        "ranks, so feeding it zeros cannot change the distribution of a shuffled board's score. "
        "This mutation surviving is a demonstration that the shuffle floor contains no "
        "football, not a hole in the gate that says so.",
    ),
    Mutation(
        "preflight finds problems and says nothing",
        "    if missing:\n        raise rank.PreflightError(",
        "    if False:\n        raise rank.PreflightError(",
        "test_preflight_names_the_missing_file_before_any_work",
    ),
    Mutation(
        "sd-without-value counts every NA instead of only the paired ones",
        '            if row[sd_i].strip() not in ("", "NA"):',
        "            if True:",
        "test_the_2015_weighted_defect_is_real_and_2016_is_clean",
    ),
    Mutation(
        "the deduplicated player keeps the LOSING row's position",
        "            position[gsis] = pos\n        position.setdefault(gsis, pos)",
        "            pass\n        position[gsis] = pos",
        "",
        "NOT COVERED. Only two players in the whole 118-scope window carry two positions under "
        "two team aliases, and neither sits where a 128-deep pool can see the difference. A "
        "gate would have to assert on those two ids, which is a gate about a fixture rather "
        "than about behaviour. Recorded as a known hole instead of papered over.",
    ),
)


def run_gates() -> tuple[int, list[str]]:
    """Returns (exit code, names of failing tests). NO EXTRA -q; see the module docstring."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", GATES,
            # NO -x. Stopping at the first failure made this sweep report "killed by the
            # wrong gate" twice, because the gate named for a mutation had simply not been
            # reached yet -- pytest had already stopped. The full list is needed to say which
            # gate actually noticed.
            "-m", "slow or not slow", "-p", "no:randomly", "-p", "no:cacheprovider",
            "--no-header", "-rf",
        ],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    failures = [
        line.split("::")[-1].split()[0]
        for line in proc.stdout.splitlines()
        if line.startswith("FAILED")
    ]
    return proc.returncode, failures


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for mutation in MUTATIONS:
            tag = "EXPECTED SURVIVOR" if mutation.expected_survivor else mutation.kills
            print(f"{mutation.label}\n    -> {tag}")
        return 0

    original = TARGET.read_text(encoding="utf-8")
    print(f"S7 MUTATION SWEEP -- {len(MUTATIONS)} mutations against {GATES}")
    print()
    baseline_code, baseline_failures = run_gates()
    if baseline_code != 0:
        print(f"BASELINE IS RED before any mutation: {baseline_failures}")
        return 1
    print("baseline green")
    print()

    survivors: list[Mutation] = []
    wrong_gate: list[tuple[Mutation, list[str]]] = []
    try:
        for mutation in MUTATIONS:
            if mutation.old not in original:
                print(f"NOT APPLICABLE  {mutation.label}")
                print("   the text it rewrites is not in the file; the mutation is stale")
                return 1
            TARGET.write_text(original.replace(mutation.old, mutation.new, 1), encoding="utf-8")
            code, failures = run_gates()
            TARGET.write_text(original, encoding="utf-8")
            if code != 0 and not failures:
                raise RuntimeError(
                    f"{mutation.label}: pytest exited {code} naming no failing test. That is a "
                    "broken run, not a kill, and counting it as one is how a sweep reports "
                    "100% against a denominator of zero."
                )
            if code == 0:
                survivors.append(mutation)  # noqa: PERF401 -- the branch below is not a filter
                verdict = "SURVIVED (expected)" if mutation.expected_survivor else "SURVIVED"
                print(f"{verdict}  {mutation.label}")
                if mutation.expected_survivor:
                    print(f"   {mutation.expected_survivor}")
            else:
                hit = mutation.kills in failures
                print(f"killed by {failures[0]}  <- {mutation.label}")
                if not hit and mutation.kills:
                    wrong_gate.append((mutation, failures))
                    print(f"   BUT the gate named for it did not fire: {mutation.kills}")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    assert TARGET.read_text(encoding="utf-8") == original, "the file was left mutated"
    unexpected = [m for m in survivors if not m.expected_survivor]
    print()
    print(f"mutations {len(MUTATIONS)}  killed {len(MUTATIONS) - len(survivors)}  "
          f"survived {len(survivors)}  unexpected survivors {len(unexpected)}")
    for mutation in unexpected:
        print(f"  UNEXPECTED SURVIVOR: {mutation.label} -- expected {mutation.kills}")
    for mutation, failures in wrong_gate:
        print(f"  KILLED BY THE WRONG GATE: {mutation.label} -- "
              f"expected {mutation.kills}, got {failures[0]}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
