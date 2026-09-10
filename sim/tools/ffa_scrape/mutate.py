"""Mutation harness: proof that the gates can go red.

WHY THIS EXISTS. Prior sessions in this repository shipped a gate satisfied by the word
`frozenset` and another that reduced to `not (True and 0 >= 3)`. Both were green, both were
worthless, and nothing in the suite could tell the difference. A test that cannot fail is not
a test, and the only way to know which kind you have is to break the code and watch.

WHAT IT CLAIMS. For every mutation below -- each one a single edit that disables exactly one
check -- at least one gate goes red, and the UNION of the gates killed covers every gate in
`sim/test_g_ffa_scrape.py`. A gate no mutation can kill is reported by name as UNKILLED,
because that gate is asserting nothing about this code.

Run it:

    uv run python -m sim.tools.ffa_scrape.mutate

It edits files in place and restores them in a `finally`, so an interrupt cannot leave a
mutated source behind. It refuses to start against a dirty tree for the same reason.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GATE = REPO / "sim" / "test_g_ffa_scrape.py"


@dataclass(frozen=True)
class Mutation:
    """One edit that disables one check."""

    name: str
    target: str  # module filename under this package
    old: str
    new: str
    # An EQUIVALENT mutant changes the code without changing what the code does, because a
    # second guard already covers the same ground. It is REQUIRED to survive: if one of
    # these is killed, the note beside it is wrong and the defence is not where it claims.
    # Recording them is the honest alternative to deleting the awkward mutation or to
    # letting a real survivor hide among them, so each one carries its reason.
    equivalent: str = ""

    @property
    def path(self) -> Path:
        return HERE / self.target


MUTATIONS: tuple[Mutation, ...] = (
    # --- verify.py: the aggregation checks, which are the ones that mattered ------------
    Mutation(
        "avg-type-mismatch-never-fires",
        "verify.py",
        "if report.avg_types != frozenset({avg}):",
        "if False:",
    ),
    Mutation(
        "avg-type-mismatch-accepts-weighted-for-anything",
        "verify.py",
        "if report.avg_types != frozenset({avg}):",
        'if report.avg_types != frozenset({avg}) and "weighted" not in report.avg_types:',
    ),
    Mutation(
        "avg-type-column-absent-never-fires",
        "verify.py",
        "if AVG_TYPE_COLUMN not in report.columns:",
        "if False:",
    ),
    Mutation(
        "avg-type-column-moved-never-fires",
        "verify.py",
        "if index != AVG_TYPE_INDEX:",
        "if False:",
    ),
    Mutation(
        "proj-gaining-an-aggregation-column-is-waved-through",
        "verify.py",
        "if AVG_TYPE_COLUMN in report.columns:\n            reasons.append(",
        "if False:\n            reasons.append(",
    ),
    Mutation(
        "sole-avg-type-guesses-when-mixed",
        "verify.py",
        "if len(self.avg_types) == 1:",
        "if self.avg_types:",
    ),
    Mutation(
        "sole-avg-type-invented-for-proj",
        "verify.py",
        "        return None\n",
        '        return "weighted"\n',
    ),
    # --- verify.py: completeness and truncation ----------------------------------------
    Mutation(
        "positions-missing-never-fires",
        "verify.py",
        "missing = NINE_POSITIONS - set(report.positions)",
        "missing = set()",
    ),
    Mutation(
        "the-nine-positions-are-eight",
        "verify.py",
        '{"QB", "RB", "WR", "TE", "K", "DST", "DL", "LB", "DB"}',
        '{"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"}',
    ),
    Mutation(
        "ragged-rows-never-fires",
        "verify.py",
        "if report.ragged:",
        "if False:",
    ),
    Mutation(
        "ragged-rows-are-not-counted",
        "verify.py",
        "            ragged += 1",
        "            pass",
    ),
    Mutation(
        "row-count-floor-never-fires",
        "verify.py",
        "if report.rows < floor:",
        "if False:",
    ),
    Mutation(
        "the-weekly-floor-equals-the-season-floor",
        "verify.py",
        '("raw", False): 120,  # weekly\n    ("proj", False): 80,',
        '("raw", False): 400,\n    ("proj", False): 200,',
    ),
    Mutation(
        "an-empty-payload-is-accepted",
        "verify.py",
        'return [f"empty-payload: {exc}"]',
        "return []",
    ),
    # --- naming.py ----------------------------------------------------------------------
    Mutation(
        "the-week-is-zero-padded",
        "naming.py",
        'return f"ffa_{kind}_{year}_wk{week}_{avg}.csv"',
        'return f"ffa_{kind}_{year}_wk{week:02d}_{avg}.csv"',
    ),
    Mutation(
        "the-kind-is-not-validated",
        "naming.py",
        "if kind not in KINDS:",
        "if False:",
    ),
    Mutation(
        "the-aggregation-is-not-validated",
        "naming.py",
        "if avg not in AVG_TYPES:",
        "if False:",
    ),
    Mutation(
        "the-year-bounds-are-not-checked",
        "naming.py",
        "if not MIN_YEAR <= year <= MAX_YEAR:",
        "if False:",
    ),
    Mutation(
        "the-week-bounds-are-not-checked",
        "naming.py",
        "if not MIN_WEEK <= week <= MAX_WEEK:",
        "if False:",
    ),
    Mutation(
        "a-chrome-suffix-parses-as-a-clean-name",
        "naming.py",
        r"(?P<avg>weighted|average|robust)\.csv$",
        r"(?P<avg>weighted|average|robust)(?: \(\d+\))?\.csv$",
        equivalent=(
            "the round-trip check in parse_filename rejects the suffixed name anyway, so "
            "widening the regex alone changes nothing observable. That guard -- not the "
            "regex -- is what actually keeps `... (1).csv` out, and "
            "`parse-does-not-round-trip-check` is the mutation that proves it."
        ),
    ),
    Mutation(
        "parse-does-not-round-trip-check",
        "naming.py",
        "if filename(kind, year, week, avg) != name:",
        "if False:",
    ),
    # --- jobs.py ------------------------------------------------------------------------
    Mutation(
        "resume-trusts-the-manifest-without-the-disk",
        "jobs.py",
        "if entry is not None and on_disk.get(name) == entry.bytes:",
        "if entry is not None:",
    ),
    Mutation(
        "resume-trusts-the-disk-without-the-size",
        "jobs.py",
        "if entry is not None and on_disk.get(name) == entry.bytes:",
        "if entry is not None and name in on_disk:",
    ),
    Mutation(
        "resume-queues-everything",
        "jobs.py",
        "if entry is not None and on_disk.get(name) == entry.bytes:\n            continue",
        "if False:\n            continue",
    ),
    Mutation(
        "the-job-list-is-not-deduplicated",
        "jobs.py",
        "if name in seen:\n            continue",
        "if False:\n            continue",
    ),
    Mutation(
        "weekly-is-offered-before-2015",
        "jobs.py",
        "WEEKLY_FROM = 2015",
        "WEEKLY_FROM = 2008",
    ),
    Mutation(
        "2026-is-treated-as-a-full-season",
        "jobs.py",
        "PARTIAL_YEARS: Mapping[int, tuple[int, ...]] = {2026: (0, 1)}",
        "PARTIAL_YEARS: Mapping[int, tuple[int, ...]] = {}",
    ),
    Mutation(
        "weighted-is-not-ordered-first",
        "jobs.py",
        'ordered_avgs = sorted(avgs, key=lambda a: (a != "weighted", AVG_TYPES.index(a)))',
        "ordered_avgs = sorted(avgs)",
    ),
    Mutation(
        "every-job-claims-it-needs-a-settings-trip",
        "jobs.py",
        'return self.avg != "weighted"',
        "return True",
    ),
    Mutation(
        "the-regular-season-is-sixteen-weeks",
        "jobs.py",
        "REGULAR_WEEKS: tuple[int, ...] = tuple(range(1, 18))",
        "REGULAR_WEEKS: tuple[int, ...] = tuple(range(1, 17))",
    ),
    Mutation(
        "the-season-window-drops-2026",
        "jobs.py",
        "SEASON_YEARS: tuple[int, ...] = tuple(range(2018, 2027))",
        "SEASON_YEARS: tuple[int, ...] = tuple(range(2018, 2026))",
    ),
    # --- manifest.py --------------------------------------------------------------------
    Mutation(
        "a-torn-tail-crashes-the-run",
        "manifest.py",
        "if index == len(lines) - 1:\n                continue",
        "if False:\n                continue",
    ),
    Mutation(
        "corruption-anywhere-is-swallowed",
        "manifest.py",
        "if index == len(lines) - 1:\n                continue",
        "if True:\n                continue",
    ),
    Mutation(
        "an-earlier-entry-wins-over-a-re-fetch",
        "manifest.py",
        'entries[payload["file"]] = ManifestEntry(',
        'entries[payload["file"]] = entries.get(payload["file"]) or ManifestEntry(',
    ),
    Mutation(
        "the-sha256-is-of-the-name-not-the-bytes",
        "manifest.py",
        "return hashlib.sha256(text.encode(\"utf-8\")).hexdigest()",
        "return hashlib.sha256(b\"\").hexdigest()",
    ),
)


def _bare(test_id: str) -> str:
    """`sim\test_g.py::test_x[case]` -> `test_x`. Parametrised cases collapse to the
    gate, because the gate is the unit a reader cares about."""
    return test_id.split("::")[-1].split("[")[0]


def _run_gates() -> tuple[int, set[str]]:
    """Return (exit code, set of failing test ids)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(GATE), "-m", "slow", "-q", "--no-header", "-p",
         "no:cacheprovider", "--tb=no", "-rf"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    failing = set(re.findall(r"^FAILED (\S+)", proc.stdout, re.M))
    # Parametrised ids collapse to the function so a mutation killing one case counts for
    # the gate; the gate is the unit a reader cares about.
    return proc.returncode, {f.split("[")[0] for f in failing}


def _all_gate_ids() -> set[str]:
    # No `-q` here. `addopts` in pyproject.toml already supplies one, and a second collapses
    # `--collect-only` to a bare count -- which silently reported "0 gates", and therefore
    # "every gate killed", on the first run of this harness.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(GATE), "-m", "slow", "--no-header",
         "--collect-only", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    ids = re.findall(r"^\S*test_g_ffa_scrape\.py::(\S+)$", proc.stdout, re.M)
    if not ids:
        raise RuntimeError(f"collected no gate ids; pytest said:\n{proc.stdout[-2000:]}")
    return {_bare(i) for i in ids}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="run one mutation by name")
    args = parser.parse_args(argv)

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", str(HERE)],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        print("refusing to mutate a dirty tree -- commit or stash first:\n" + dirty)
        return 2

    baseline_code, baseline_failures = _run_gates()
    if baseline_code != 0:
        print(f"baseline is not green ({baseline_failures}); fix that before mutating")
        return 2
    every_gate = _all_gate_ids()
    print(f"baseline: green, {len(every_gate)} gates\n")

    killed: set[str] = set()
    survivors: list[str] = []
    wrong_notes: list[str] = []
    selected = [m for m in MUTATIONS if args.only is None or m.name == args.only]
    for mutation in selected:
        original = mutation.path.read_text(encoding="utf-8")
        if mutation.old not in original:
            print(f"  !! {mutation.name}: pattern not found in {mutation.target}")
            survivors.append(mutation.name)
            continue
        if original.count(mutation.old) != 1:
            print(f"  !! {mutation.name}: pattern is not unique in {mutation.target}")
            survivors.append(mutation.name)
            continue
        try:
            mutation.path.write_text(
                original.replace(mutation.old, mutation.new), encoding="utf-8"
            )
            code, failures = _run_gates()
        finally:
            mutation.path.write_text(original, encoding="utf-8")
        if code == 0:
            if mutation.equivalent:
                print(f"  equivalent  {mutation.name}")
            else:
                print(f"  SURVIVED    {mutation.name}")
                survivors.append(mutation.name)
        else:
            killed |= failures
            if mutation.equivalent:
                print(f"  NOT-EQUIVALENT {mutation.name}: killed, so its note is wrong")
                wrong_notes.append(mutation.name)
            else:
                print(f"  killed by {len(failures):>2}  {mutation.name}")

    unkilled = sorted(every_gate - killed)
    equivalents = [m.name for m in selected if m.equivalent]
    print(f"\nmutations: {len(selected)}, equivalent-by-design: {len(equivalents)}, "
          f"survived: {len(survivors)}")
    print(f"gates killed by at least one mutation: {len(killed)}/{len(every_gate)}")
    for name in survivors:
        print(f"  SURVIVOR: {name}")
    for name in wrong_notes:
        print(f"  WRONG EQUIVALENCE NOTE: {name}")
    for gate in unkilled:
        print(f"  UNKILLED: {gate}")
    return 0 if not survivors and not unkilled and not wrong_notes else 1


if __name__ == "__main__":
    raise SystemExit(main())
