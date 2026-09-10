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
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GATE = REPO / "sim" / "test_g_ffa_scrape.py"

# How recently the corpus manifest must have been written for a scrape to count as
# in flight. A file takes about 18 seconds, so two minutes is comfortably clear.
SCRAPE_IDLE_SECONDS = 120.0


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
        '    elif kind == "proj" and AVG_TYPE_COLUMN in report.columns:',
        "    elif False:",
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
        "    missing = CORE_POSITIONS - present",
        "    missing = set()",
    ),
    Mutation(
        "idp-is-required-again",
        "verify.py",
        "    missing = CORE_POSITIONS - present",
        "    missing = NINE_POSITIONS - present",
    ),
    Mutation(
        "partial-idp-is-waved-through",
        "verify.py",
        "if idp and idp != IDP_POSITIONS:",
        "if False:",
    ),
    Mutation(
        "the-core-set-is-empty",
        "verify.py",
        'CORE_POSITIONS: Final[frozenset[str]] = frozenset({"QB", "RB", "WR", "TE", "K", "DST"})',
        "CORE_POSITIONS: Final[frozenset[str]] = frozenset()",
    ),
    Mutation(
        "idp-is-counted-as-core",
        "verify.py",
        'IDP_POSITIONS: Final[frozenset[str]] = frozenset({"DL", "LB", "DB"})',
        "IDP_POSITIONS: Final[frozenset[str]] = frozenset()",
    ),
    Mutation(
        "the-season-check-never-fires",
        "verify.py",
        "if report.season_years and report.season_years != frozenset({str(year)}):",
        "if False:",
    ),
    Mutation(
        "the-season-check-fires-on-a-match",
        "verify.py",
        "if report.season_years and report.season_years != frozenset({str(year)}):",
        "if report.season_years:",
    ),
    Mutation(
        "the-week-check-never-fires",
        "verify.py",
        "if report.weeks and report.weeks != frozenset({str(week)}):",
        "if False:",
    ),
    Mutation(
        "the-week-check-fires-on-a-match",
        "verify.py",
        "if report.weeks and report.weeks != frozenset({str(week)}):",
        "if report.weeks:",
    ),
    Mutation(
        "an-NA-scope-column-is-read-as-a-real-value",
        "verify.py",
        '_ABSENT: Final[frozenset[str]] = frozenset({"NA", "", "N/A", "null"})',
        "_ABSENT: Final[frozenset[str]] = frozenset()",
    ),
    Mutation(
        "the-scope-columns-are-never-read",
        "verify.py",
        "        if year_index is not None and row[year_index] not in _ABSENT:",
        "        if False:",
    ),
    Mutation(
        "an-unknown-kind-raises-again",
        "verify.py",
        "    if kind not in KNOWN_KINDS:",
        "    if False:",
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
        "if entry is None or on_disk.get(name) != entry.bytes:",
        "if entry is None:",
    ),
    Mutation(
        "resume-trusts-the-disk-without-the-size",
        "jobs.py",
        "if entry is None or on_disk.get(name) != entry.bytes:",
        "if entry is None or name not in on_disk:",
    ),
    Mutation(
        "resume-queues-everything",
        "jobs.py",
        "        if entry is None or on_disk.get(name) != entry.bytes:",
        "        if True:",
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
        "a-manifest-line-without-a-witness-field-crashes-the-load",
        "manifest.py",
        '            witness_sha256=payload.get("witness_sha256"),',
        '            witness_sha256=payload["witness_sha256"],',
    ),
    Mutation(
        "the-sha256-is-of-the-name-not-the-bytes",
        "manifest.py",
        "return hashlib.sha256(text.encode(\"utf-8\")).hexdigest()",
        "return hashlib.sha256(b\"\").hexdigest()",
    ),
    # --- OVER-FIRING. Every mutation above disables a check, and a CONTROL -- a gate that
    # asserts a good payload is ACCEPTED -- survives all of them by construction. Without
    # these, a verifier rewritten to reject everything would pass the whole suite, and the
    # controls would be exactly the tests-that-cannot-fail this harness exists to find.
    Mutation(
        "the-aggregation-check-fires-on-a-match-too",
        "verify.py",
        "if report.avg_types != frozenset({avg}):",
        "if True:",
    ),
    Mutation(
        "the-position-check-fires-on-a-complete-file",
        "verify.py",
        "    missing = CORE_POSITIONS - present",
        '    missing = {"XX"}',
    ),
    Mutation(
        "the-nine-positions-are-ten",
        "verify.py",
        '{"QB", "RB", "WR", "TE", "K", "DST", "DL", "LB", "DB"}',
        '{"QB", "RB", "WR", "TE", "K", "DST", "DL", "LB", "DB", "FB"}',
    ),
    Mutation(
        "the-row-floor-rejects-every-file",
        "verify.py",
        "if report.rows < floor:",
        "if True:",
    ),
    Mutation(
        "the-weekly-floor-is-above-the-season-floor",
        "verify.py",
        '("raw", False): 120,  # weekly\n    ("proj", False): 80,',
        '("raw", False): 9000,\n    ("proj", False): 9000,',
    ),
    Mutation(
        "a-proj-file-is-rejected-for-lacking-an-aggregation-column",
        "verify.py",
        '    elif kind == "proj" and AVG_TYPE_COLUMN in report.columns:',
        '    elif kind == "proj" and AVG_TYPE_COLUMN not in report.columns:',
    ),
    Mutation(
        "the-ragged-check-fires-on-a-clean-file",
        "verify.py",
        "if report.ragged:",
        "if report.ragged >= 0:",
    ),
    Mutation(
        "the-filename-ignores-its-arguments",
        "naming.py",
        'return f"ffa_{kind}_{year}_wk{week}_{avg}.csv"',
        'return "ffa_raw_2019_wk0_weighted.csv"',
    ),
    Mutation(
        "parse-accepts-a-name-it-cannot-read",
        "naming.py",
        "if match is None:",
        "if False:",
    ),
    Mutation(
        "plan-queues-nothing-ever",
        "jobs.py",
        "    return queued",
        "    return []",
    ),
    Mutation(
        "2026-is-refused-its-one-played-week",
        "jobs.py",
        "PARTIAL_YEARS: Mapping[int, tuple[int, ...]] = {2026: (0, 1)}",
        "PARTIAL_YEARS: Mapping[int, tuple[int, ...]] = {2026: (0,)}",
    ),
    Mutation(
        "weekly-starts-a-year-late",
        "jobs.py",
        "WEEKLY_FROM = 2015",
        "WEEKLY_FROM = 2016",
    ),
    Mutation(
        "every-job-claims-it-skips-the-settings-trip",
        "jobs.py",
        'return self.avg != "weighted"',
        "return False",
    ),
    # --- runner.py: does the runner actually OBEY the checks? ---------------------------
    Mutation(
        "a-rejected-payload-is-written-anyway",
        "runner.py",
        "return (result.text if not reasons else None), reasons",
        "return result.text, reasons",
    ),
    Mutation(
        "there-is-no-retry",
        "runner.py",
        "for scale in (1.0, RETRY_SCALE):",
        "for scale in (1.0,):",
    ),
    Mutation(
        "a-lost-session-is-not-re-established",
        "runner.py",
        "                driver.establish()",
        "                pass",
    ),
    Mutation(
        "the-recovery-cap-is-removed",
        "runner.py",
        "if consecutive_recoveries > MAX_CONSECUTIVE_RECOVERIES:\n                    raise",
        "if False:\n                    raise",
    ),
    Mutation(
        "the-manifest-is-never-appended",
        "runner.py",
        "        append_entry(\n            manifest_path,",
        "        _ = (\n            manifest_path,",
    ),
    Mutation(
        "the-payload-is-written-in-text-mode",
        "runner.py",
        "part.write_bytes(payload)",
        "part.write_text(text)",
    ),
    Mutation(
        "the-part-file-is-left-behind",
        "runner.py",
        "os.replace(part, data_dir / name)",
        "(data_dir / name).write_bytes(payload)",
    ),
    Mutation(
        "an-html-login-page-is-not-recognised",
        "runner.py",
        'return head.startswith("<!doctype html") or head.startswith("<html")',
        "return False",
    ),
    Mutation(
        "the-runner-asks-for-weighted-whatever-the-job-says",
        "runner.py",
        "            job.avg,\n",
        '            "weighted",\n',
    ),
    # --- driver.py: the ORDER, which is the mechanism of the original defect -------------
    # The ORIGINAL defect, restored exactly: skip the Settings trip for any weighted job on
    # the strength of a year change that may not have happened. This is the logic the live
    # probe caught serving `robust` for a `weighted` request.
    Mutation(
        "the-driver-goes-back-to-skipping-the-trip-for-weighted",
        "driver.py",
        "if force_settings_trip or self._effective_avg != avg:",
        'if avg != "weighted":',
    ),
    # The other half: a real year change no longer buys the reset, so every weighted job
    # pays for a trip it does not need. Correct output, wrong cost model.
    Mutation(
        "a-year-change-no-longer-clears-the-effective-aggregation",
        "driver.py",
        "if year_before != str(year):",
        "if False:",
    ),
    Mutation(
        "the-year-is-read-back-as-whatever-we-are-about-to-write",
        "driver.py",
        "        year_before = self.read_input(YEAR_INPUT)",
        "        year_before = str(year)",
    ),
    Mutation(
        "the-aggregation-is-set-without-the-settings-trip",
        "driver.py",
        "            self.click_tab(TAB_SETTINGS)\n"
        "            self.set_input(AVG_INPUT, avg, self.settles.after_avg)\n"
        "            self.click_tab(TAB_PROJ)\n",
        "            self.set_input(AVG_INPUT, avg, self.settles.after_avg)\n",
    ),
    Mutation(
        "weighted-pays-for-a-settings-trip-it-does-not-need",
        "driver.py",
        "        if force_settings_trip or self._effective_avg != avg:",
        "        if True:",
    ),
    Mutation(
        "a-pending-message-queue-joins-the-stuck-set",
        "driver.py",
        '                and not name.startswith("$")',
        "                and True",
    ),
    Mutation(
        "everything-busy-is-stuck-immediately",
        "driver.py",
        "                and now - first >= self.settles.stuck_after",
        "                and True",
    ),
    Mutation(
        "the-session-regex-only-reads-the-relative-href",
        "driver.py",
        '_SESSION_RE = re.compile(r"(?:^|/)session/([^/?#]+)/")',
        '_SESSION_RE = re.compile(r"^session/([^/?#]+)/")',
    ),
    Mutation(
        "the-per-write-read-back-is-dropped",
        "driver.py",
        "if seen != value:",
        "if False:",
    ),
    Mutation(
        "the-final-combined-read-back-is-dropped",
        "driver.py",
        "if drifted:",
        "if False:",
    ),
    Mutation(
        "the-session-token-is-not-compared",
        "driver.py",
        "if self._session_token is not None and token != self._session_token:",
        "if False:",
    ),
    Mutation(
        "modals-are-never-checked-for",
        "driver.py",
        "        self.clear_modal()\n        # A modest timeout",
        "        # A modest timeout",
    ),
    Mutation(
        "a-modal-that-will-not-close-is-treated-as-closed",
        "driver.py",
        '            raise ModalBlocked(f"a modal is up and has no dismiss control: {text!r}")',
        "            return text",
    ),
    Mutation(
        "a-modal-that-reappears-is-treated-as-closed",
        "driver.py",
        '        if still["present"]:',
        "        if False:",
    ),
    Mutation(
        "a-torn-tail-is-not-healed-before-appending",
        "manifest.py",
        "        if not raw.endswith(",
        "        if False and raw.endswith(",
    ),
    Mutation(
        "a-torn-tail-is-terminated-instead-of-dropped",
        "manifest.py",
        '            path.write_bytes(raw[: cut + 1] if cut != -1 else b"")',
        # RAW string. A non-raw one puts an ACTUAL newline inside the b"..." literal and the
        # mutated module is a syntax error rather than a behavioural change -- pytest cannot
        # even collect, and a collection error is not evidence that any gate caught anything.
        r'            path.write_bytes(raw + b"\n")',
    ),
    Mutation(
        "plan-ignores-the-digest",
        "jobs.py",
        "        if digests is not None and digests.get(name) != entry.sha256:",
        "        if False:",
    ),
    Mutation(
        "plan-requires-a-digest-that-can-never-match",
        "jobs.py",
        "        if digests is not None and digests.get(name) != entry.sha256:",
        "        if digests is not None:",
    ),
    Mutation(
        "switch-kind-checks-only-the-file-type",
        "driver.py",
        "        self._assert_scope(year, week, kind)",
        "        self.assert_same_session()",
    ),
    Mutation(
        "establish-accepts-a-session-with-no-token",
        "driver.py",
        "        if self._session_token is None:",
        "        if False:",
    ),
    Mutation(
        "the-combined-read-back-drops-the-aggregation",
        "driver.py",
        "        if avg is not None:",
        "        if False:",
    ),
    Mutation(
        "wait-idle-measures-appearance-not-continuity",
        "driver.py",
        "            for name in list(since):",
        "            for name in []:",
    ),
    Mutation(
        "the-modal-probe-dismisses-too",
        "driver.py",
        "        still = self.page.evaluate(_MODAL_PROBE_JS)",
        "        still = self.page.evaluate(_MODAL_DISMISS_JS)",
    ),
    Mutation(
        "a-locked-control-does-not-stop-the-start",
        "driver.py",
        "if expect_login and text == LOCKED_TEXT:",
        "if False:",
    ),
    Mutation(
        "readiness-is-presence-not-population",
        "driver.py",
        "        self.page.wait_for_function(\n"
        "            _READY_JS, timeout=self.settles.ready_timeout * 1000\n"
        "        )",
        "        pass",
    ),
    Mutation(
        "the-idle-baseline-is-never-taken",
        "driver.py",
        '        self._idle_baseline = frozenset(self.page.evaluate(_BUSY_JS)["busy"])',
        "        self._idle_baseline = frozenset()",
    ),
    Mutation(
        "the-idle-baseline-swallows-everything",
        "driver.py",
        'busy = set(state["busy"]) - self._idle_baseline',
        "busy = set()",
    ),
    Mutation(
        "a-pending-message-queue-is-not-busy",
        "driver.py",
        '        if state["pending"]:',
        "        if False:",
    ),
    Mutation(
        "the-session-regex-only-reads-the-absolute-href",
        "driver.py",
        '_SESSION_RE = re.compile(r"(?:^|/)session/([^/?#]+)/")',
        '_SESSION_RE = re.compile(r"/session/([^/?#]+)/")',
    ),
    Mutation(
        "a-locked-control-does-not-stop-a-fetch",
        "driver.py",
        "        if text == LOCKED_TEXT:\n"
        '            raise NotLoggedIn(f"the download control reads {text!r} mid-run")',
        "        if False:\n"
        '            raise NotLoggedIn(f"the download control reads {text!r} mid-run")',
    ),
)

# Gates about the REPOSITORY rather than about this package: no edit to a module here can
# make them red, so leaving them in the coverage denominator would be dishonest in the other
# direction -- a permanent UNKILLED that means nothing. They are exercised by failure
# injection instead (add a CSV, `git add -f`, watch it go red), which is recorded in the PR.
EXTERNAL_GATES: dict[str, str] = {
    "test_no_csv_is_tracked_anywhere_in_the_repository":
        "about the git index; injected by `git add -f` on a CSV",
    "test_the_corpus_directory_is_ignored_by_git":
        "about .gitignore; injected by the same",
    "test_the_manifest_and_readme_are_the_only_things_meant_to_be_committed":
        "about the git index; injected by the same",
    "test_the_synthetic_raw_fixture_matches_a_real_export":
        "reconciles the fixtures against a real export; skips where the corpus is absent",
    # These three assert that FakeShinyPage reproduces the app's MEASURED behaviour. They
    # are the model's controls, not the driver's -- no edit to driver.py can change what the
    # model does, and if one of them ever passes wrongly the whole driver suite is measuring
    # a fiction. `probe` re-measures the same three against the live app before every run,
    # which is where that claim is actually settled.
    "test_setting_the_aggregation_before_the_year_would_lose_it":
        "model control for behaviour 1; re-measured live by `probe`",
    "test_an_aggregation_set_without_the_round_trip_does_not_take":
        "model control for behaviour 2; re-measured live by `probe`",
    "test_a_fresh_load_reads_2026_week_0_proj":
        "model control for the reload defaults; re-measured live by `probe`",
    # META-GATES. These are about the GATE FILE, not about this package: one reads its own
    # source and one inspects the test fixture's settles. No edit to a module here can make
    # either fail, and both are injected instead -- add a bare `driver_mod.Settles()` to the
    # gate file and watch them go red.
    "test_no_offline_gate_sleeps_through_a_production_settle":
        "about the gate file's own fixture; injected by un-zeroing INSTANT",
    "test_this_module_never_builds_a_settles_with_production_defaults":
        "reads the gate file's own source; injected by adding a bare Settles(",
    # Two more model controls. Both assert what FakeShinyPage does, not what the driver
    # does: one that a real click against a modal raises the way the live one did, and one
    # that the probe handler never dismisses. No edit to a module here can change either.
    "test_a_modal_blocks_a_real_click_the_way_the_live_one_did":
        "model control: the fake reproduces the live click interception",
    "test_the_modal_probe_never_dismisses":
        "model control: the fake's probe handler is read-only, like the JS it stands for",
}


def _bare(test_id: str) -> str:
    """`sim\test_g.py::test_x[case]` -> `test_x`. Parametrised cases collapse to the
    gate, because the gate is the unit a reader cares about."""
    return test_id.split("::")[-1].split("[")[0]


def _run_gates() -> tuple[int, set[str]]:
    """Return (exit code, set of failing gate names).

    No `-q` here either, and for the same reason as `_all_gate_ids`: `addopts` supplies one,
    a second makes it `-qq`, and `-qq` drops the `FAILED ...` lines that `-rf` exists to
    print. The harness then saw a red run with an EMPTY failure set and under-counted which
    gates each mutation killed -- which is the same class of defect as the one it is here to
    find, in the instrument rather than in the code.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(GATE), "-m", "slow", "--no-header", "-p",
         "no:cacheprovider", "--tb=no", "-rf"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    failing = set(re.findall(r"^FAILED \S*test_g_ffa_scrape\.py::(\S+)", proc.stdout, re.M))
    if proc.returncode != 0 and not failing:
        raise RuntimeError(f"a red run named no failures:\n{proc.stdout[-3000:]}")
    # Parametrised ids collapse to the function so a mutation killing one case counts for
    # the gate; the gate is the unit a reader cares about.
    return proc.returncode, {_bare(f) for f in failing}


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
    parser.add_argument(
        "--force-beside-a-run",
        action="store_true",
        help="mutate even though the corpus manifest was written recently",
    )
    args = parser.parse_args(argv)

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", str(HERE)],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        print("refusing to mutate a dirty tree -- commit or stash first:\n" + dirty)
        return 2

    # REFUSE TO RUN BESIDE A SCRAPE. This harness edits the modules a run imports, and it
    # leaves them mutated for the length of a pytest run. A scrape already in flight is
    # safe -- Python compiled those modules at import and never re-reads them -- but two
    # things near it are NOT: a scrape STARTED mid-sweep would load a mutated verifier and
    # write files nothing had really checked, and a `git add -A` at the wrong moment would
    # commit the mutation. Neither is hypothetical; this session did the second one to
    # itself and had to notice.
    #
    # A manifest touched in the last two minutes means a run is writing. Two minutes is
    # comfortably longer than the ~18s a file takes.
    manifest = REPO / "sim" / "data" / "ffa_corpus" / "manifest.jsonl"
    if manifest.exists():
        idle = time.time() - manifest.stat().st_mtime
        if idle < SCRAPE_IDLE_SECONDS:
            print(
                f"refusing to mutate while a scrape is running -- {manifest.name} was "
                f"written {idle:.0f}s ago. Wait for it, or pass --force-beside-a-run if "
                "you are certain there is none."
            )
            if not args.force_beside_a_run:
                return 2

    baseline_code, baseline_failures = _run_gates()
    if baseline_code != 0:
        print(f"baseline is not green ({baseline_failures}); fix that before mutating")
        return 2
    # FAIL FAST ON STALE PATTERNS. A mutation whose `old` no longer appears in its target
    # tests nothing, and the source moves under these constantly -- splitting the position
    # check and adding effective-aggregation tracking stranded five of them at once. They
    # were reported as SURVIVORS, which is the right conservative call, but only after a
    # full sweep. Checking up front names all of them in a second.
    stale = []
    for mutation in MUTATIONS:
        count = mutation.path.read_text(encoding="utf-8").count(mutation.old)
        if count != 1:
            stale.append(f"{mutation.name} ({mutation.target}): matches {count}x, want 1")
    if stale:
        print("stale or ambiguous mutation patterns -- these test nothing:")
        for line in stale:
            print(f"  {line}")
        return 2

    # A mutation must produce VALID PYTHON. One that does not is a syntax error, pytest
    # cannot collect at all, and a collection error is not evidence that any gate caught
    # anything -- `_run_gates` refuses to score it, which is how this was found: a non-raw
    # `"\n"` in a replacement put a real newline inside a bytes literal.
    unparseable = []
    for mutation in MUTATIONS:
        source = mutation.path.read_text(encoding="utf-8")
        try:
            compile(source.replace(mutation.old, mutation.new, 1), mutation.target, "exec")
        except SyntaxError as exc:
            unparseable.append(f"{mutation.name} ({mutation.target}): {exc}")
    if unparseable:
        print("mutations that do not produce valid Python -- these test nothing:")
        for line in unparseable:
            print(f"  {line}")
        return 2

    collected = _all_gate_ids()
    stale = sorted(set(EXTERNAL_GATES) - collected)
    if stale:
        print(f"EXTERNAL_GATES names gates that no longer exist: {stale}")
        return 2
    every_gate = collected - set(EXTERNAL_GATES)
    print(f"baseline: green, {len(every_gate)} gates in scope")
    for name, reason in sorted(EXTERNAL_GATES.items()):
        print(f"  out of scope: {name} -- {reason}")
    print()

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

    killed &= every_gate  # an external gate caught in the blast is not coverage of scope
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
