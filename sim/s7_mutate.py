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
ADJUDICATION = REPO / "sim" / "s7_phase2.py"
PHASE4 = REPO / "sim" / "s7_phase4.py"
GATES = "sim/test_g_s7.py"
ADJUDICATION_GATES = "sim/test_g_s7_adjudication.py"


@dataclass(frozen=True, slots=True)
class Mutation:
    label: str
    old: str
    new: str
    kills: str  # the gate expected to fail, by name fragment
    expected_survivor: str = ""  # non-empty means this mutation SHOULD survive, and why
    target: str = "weekly"  # which file to mutate: weekly | adjudication | phase4


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
    # --- the adjudication, which nothing tested until the review said so ---------------------
    Mutation(
        "leave-one-season-out lets a season choose its own strength",
        "        others = [scope for scope in base if scope[0] != held]",
        "        others = list(base)",
        "test_loso_never_lets_a_season_choose_its_own_strength",
        target="adjudication",
    ),
    Mutation(
        "0.0 is dropped from the strength grid, so a useless term must intervene",
        "GRID: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10, 0.20)",
        "GRID: tuple[float, ...] = (0.02, 0.05, 0.10, 0.20)",
        "test_loso_selects_zero_when_no_strength_helps",
        target="adjudication",
    ),
    Mutation(
        "the reference-set p loses its +1, so a term can score p = 0",
        "    return (1 + sum(1 for f in usable if f >= observed)) / (1 + len(usable))",
        "    return sum(1 for f in usable if f >= observed) / len(usable)",
        "test_reference_p_is_smallest_when_the_term_beats_every_draw",
        target="adjudication",
    ),
    Mutation(
        "the harm p is the same one-sided test as the improvement p",
        "    return (1 + sum(1 for f in usable if f <= observed)) / (1 + len(usable))",
        "    return (1 + sum(1 for f in usable if f >= observed)) / (1 + len(usable))",
        "test_harm_p_is_the_mirror_and_the_first_version_had_it_backwards",
        target="adjudication",
    ),
    Mutation(
        "the null hit rate ignores ties and returns a flat 2/41",
        "    usable = [f for f in floor if f == f]\n    if not usable or observed != observed:",
        "    return 2 / 41\n    usable = [f for f in floor if f == f]\n"
        "    if not usable or observed != observed:",
        "test_null_hit_rate_is_zero_when_the_floor_ties_at_the_maximum",
        target="adjudication",
    ),
    Mutation(
        "the floor goes back to a hash instead of permuting the term's own values",
        "    held = [values[pid] for pid in covered]\n    rng.shuffle(held)",
        "    held = [rng.random() for _ in covered]",
        "test_the_floor_preserves_the_terms_own_marginal_distribution",
        target="adjudication",
    ),
    Mutation(
        "a position-level constant is dealt to individual players",
        "    if frozen and frozen >= {pos for pos in POSITIONS if any(",
        "    if False and frozen >= {pos for pos in POSITIONS if any(",
        "test_a_position_level_constant_is_permuted_ACROSS_positions",
        target="adjudication",
    ),
    Mutation(
        "materiality goes back to the magnitude of a term's own damage",
        "    material = bool(qualifying) and max(value for _where, value in qualifying) "
        ">= MATERIAL",
        "    material = bool(qualifying) and max(abs(value) for _where, value in qualifying) "
        ">= MATERIAL",
        "",
        "EQUIVALENT AGAINST THIS GATE SET, and the reason is worth recording. The old defect "
        "took the max over the BOARD effect and the LOCUS effects whether or not they "
        "qualified; this mutation only restores the `abs`, and a value that reached "
        "`qualifying` is already positive, so `abs` changes nothing. The defect was the "
        "unqualified membership, not the absolute value, and the gate targets the membership.",
        target="adjudication",
    ),
    Mutation(
        "an off-locus hit is promoted to a resolution",
        "    if qualifying:\n        verdict = \"RESOLVES\" if material else "
        "\"resolves but immaterial\"",
        "    if qualifying or off_locus:\n        verdict = \"RESOLVES\" if material else "
        "\"resolves but immaterial\"",
        "test_an_off_locus_hit_is_a_lead_and_never_a_resolution",
        target="adjudication",
    ),
    Mutation(
        "the harm branch goes back to testing the improvement p",
        "        if record.get(\"harm_p_position\", {}).get(pos, 1.0) <= 0.05",
        "        if record[\"p_position\"].get(pos, 1.0) <= 0.05",
        "test_a_material_harm_is_reported_as_a_harm",
        target="adjudication",
    ),
    Mutation(
        "phase 4 accepts any verdict, not only RESOLVES",
        "            if verdict != \"RESOLVES\":",
        "            if verdict == \"never\":",
        "test_only_a_RESOLVES_record_becomes_a_survivor",
        target="phase4",
    ),
    Mutation(
        "phase 4 averages the selected strengths instead of taking the mode",
        "            lam = max(set(lams), key=lams.count)",
        "            lam = sum(lams) / len(lams)",
        "test_the_modal_lambda_is_a_grid_point_and_never_an_average",
        target="phase4",
    ),
    Mutation(
        "an in-season term is allowed onto the draft board",
        '        return self.source == "phase2"',
        "        return True",
        "test_an_in_season_term_is_never_draft_capable",
        target="phase4",
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


TARGETS = {"weekly": (TARGET, GATES), "adjudication": (ADJUDICATION, ADJUDICATION_GATES),
           "phase4": (PHASE4, ADJUDICATION_GATES)}


def run_gates(gates: str = GATES) -> tuple[int, list[str]]:
    """Returns (exit code, names of failing tests). NO EXTRA -q; see the module docstring."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", gates,
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

    originals = {name: path.read_text(encoding="utf-8") for name, (path, _g) in TARGETS.items()}
    print(f"S7 MUTATION SWEEP -- {len(MUTATIONS)} mutations across "
          f"{len({m.target for m in MUTATIONS})} targets")
    for name, (path, gates) in TARGETS.items():
        print(f"  {name}: {path.name} against {gates}")
    print()
    for name, (_path, gates) in TARGETS.items():
        baseline_code, baseline_failures = run_gates(gates)
        if baseline_code != 0:
            print(f"BASELINE IS RED for {name} before any mutation: {baseline_failures}")
            return 1
    print("baseline green on every target")
    print()

    survivors: list[Mutation] = []
    wrong_gate: list[tuple[Mutation, list[str]]] = []
    try:
        for mutation in MUTATIONS:
            path, gates = TARGETS[mutation.target]
            original = originals[mutation.target]
            if mutation.old not in original:
                print(f"NOT APPLICABLE  {mutation.label}")
                print("   the text it rewrites is not in the file; the mutation is stale")
                return 1
            path.write_text(original.replace(mutation.old, mutation.new, 1), encoding="utf-8")
            code, failures = run_gates(gates)
            path.write_text(original, encoding="utf-8")
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
        for name, (path, _g) in TARGETS.items():
            path.write_text(originals[name], encoding="utf-8")

    for name, (path, _g) in TARGETS.items():
        assert path.read_text(encoding="utf-8") == originals[name], f"{name} was left mutated"
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
