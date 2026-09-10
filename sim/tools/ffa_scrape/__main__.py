"""Command line for the FFA corpus scraper.

    uv run python -m sim.tools.ffa_scrape login     # headed; a HUMAN signs in, once
    uv run python -m sim.tools.ffa_scrape probe     # re-measure the five behaviours
    uv run python -m sim.tools.ffa_scrape run --stage weekly-weighted
    uv run python -m sim.tools.ffa_scrape status    # coverage, and named gaps

`login` never touches the password. It opens the app in a visible browser and waits for the
download control to stop reading "Subscribe to download"; the persistent profile carries the
session into every later headless run.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .driver import (
    APP_URL,
    AVG_INPUT,
    KIND_INPUT,
    LOCKED_TEXT,
    WEEK_INPUT,
    YEAR_INPUT,
    Settles,
    ShinyDriver,
    open_context,
)
from .jobs import STAGE_ORDER, STAGES, Job, plan
from .manifest import MANIFEST_NAME, load_manifest
from .naming import parse_filename
from .runner import run_jobs
from .verify import IDP_POSITIONS, inspect_csv, verify_payload

REPO = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO / "sim" / "data" / "ffa_corpus"
# The profile holds a live session cookie for a paid account. `data/sim-cache/` is gitignored
# wholesale, which is what makes it the right home for a per-machine credential store.
DEFAULT_PROFILE = REPO / "data" / "sim-cache" / "ffa_profile"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _on_disk(data_dir: Path) -> dict[str, int]:
    if not data_dir.exists():
        return {}
    return {p.name: p.stat().st_size for p in data_dir.glob("ffa_*.csv")}


def _stage_jobs(stage: str) -> list[Job]:
    if stage == "all":
        return [job for name in STAGE_ORDER for job in STAGES[name]]
    return list(STAGES[stage])


# ---------------------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------------------


def cmd_login(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = open_context(pw, args.profile, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        driver = ShinyDriver(page, Settles())
        print(f"opening {APP_URL} -- sign in yourself; this tool never handles a password.")
        driver.establish(expect_login=False)
        print(f"waiting up to {args.wait / 60:.0f} minutes for the download control to "
              f"stop reading {LOCKED_TEXT!r}.")

        # NEVER reload while a human is typing. An earlier version of this polled with a
        # `page.reload()` every two seconds, which would have wiped the login form mid
        # password. The control is a Shiny output and updates reactively, so polling its
        # text is enough; the page may also navigate during sign-in, and a read that throws
        # is a page in transit rather than a failure.
        deadline = time.time() + args.wait
        last = None
        while time.time() < deadline:
            try:
                _, text = driver.download_control()
            except Exception:  # noqa: BLE001 -- mid-navigation reads throw; keep waiting
                text = None
            if text and text != last:
                print(f"  control reads {text!r}")
                last = text
            if text and text != LOCKED_TEXT:
                print(f"logged in. profile saved at {args.profile}")
                context.close()
                return 0
            time.sleep(3.0)
        print(f"gave up after {args.wait}s; the control last read {last!r}")
        context.close()
        return 1


# ---------------------------------------------------------------------------------------
# probe -- re-measure the five behaviours the driver is shaped around
# ---------------------------------------------------------------------------------------


def cmd_probe(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    findings: list[tuple[str, str]] = []

    def record(name: str, verdict: str) -> None:
        findings.append((name, verdict))
        print(f"  {name}: {verdict}")

    with sync_playwright() as pw:
        context = open_context(pw, args.profile, headless=args.headless)
        page = context.pages[0] if context.pages else context.new_page()
        driver = ShinyDriver(page, Settles())
        driver.establish()

        print("\n-- defaults on a fresh load (what a session reload resets to) --")
        defaults = {
            "year": driver.read_input(YEAR_INPUT),
            "week": driver.read_input(WEEK_INPUT),
            "kind": driver.read_input(KIND_INPUT),
        }
        record("fresh-load-defaults", str(defaults))

        print("\n-- behaviour 1: does a year change reset the aggregation? --")
        driver.click_tab("tab_settings")
        driver.set_input(AVG_INPUT, "robust", driver.settles.after_avg)
        before = driver.read_input(AVG_INPUT)
        driver.click_tab("tab_proj")
        driver.set_input(YEAR_INPUT, "2019", driver.settles.after_year)
        driver.click_tab("tab_settings")
        after = driver.read_input(AVG_INPUT)
        driver.click_tab("tab_proj")
        record(
            "year-change-resets-aggregation",
            f"aggregation was {before!r} before the year change and {after!r} after "
            f"-- {'RESET (premise holds)' if after != before else 'NOT reset (premise refuted)'}",
        )

        print("\n-- behaviour 3: a weighted season file, no Settings trip --")
        started = time.time()
        driver.prepare("raw", 2019, 0, "weighted")
        payload = driver.fetch_payload()
        weighted_seconds = time.time() - started
        reasons = verify_payload(payload.text, kind="raw", year=2019, week=0, avg="weighted")
        report = inspect_csv(payload.text) if payload.text else None
        record(
            "weighted-season-2019",
            f"{weighted_seconds:.1f}s, {report.rows if report else 0} rows, "
            f"avg_type={report.sole_avg_type if report else None}, "
            f"positions={sorted(report.positions) if report else []}, "
            f"reasons={reasons or 'none'}",
        )

        print("\n-- behaviour 2: an aggregation only lands after a Settings round trip --")
        for avg in ("average", "robust"):
            started = time.time()
            driver.prepare("raw", 2019, 0, avg)
            payload = driver.fetch_payload()
            seconds = time.time() - started
            reasons = verify_payload(payload.text, kind="raw", year=2019, week=0, avg=avg)
            report = inspect_csv(payload.text) if payload.text else None
            record(
                f"{avg}-season-2019",
                f"{seconds:.1f}s, {report.rows if report else 0} rows, "
                f"avg_type={report.sole_avg_type if report else None}, "
                f"reasons={reasons or 'none'}",
            )

        print("\n-- weekly: does it exist, and how big is it? --")
        for year, week in ((2019, 5), (2025, 12)):
            started = time.time()
            driver.prepare("raw", year, week, "weighted")
            payload = driver.fetch_payload()
            seconds = time.time() - started
            reasons = verify_payload(payload.text, kind="raw", year=year, week=week, avg="weighted")
            report = inspect_csv(payload.text) if payload.text else None
            record(
                f"weekly-{year}-wk{week}",
                f"{seconds:.1f}s, {report.rows if report else 0} rows, "
                f"avg_type={report.sole_avg_type if report else None}, "
                f"positions={sorted(report.positions) if report else []}, "
                f"reasons={reasons or 'none'}",
            )

        print("\n-- behaviour 4: a proj file carries no aggregation column --")
        driver.prepare("proj", 2019, 0, "weighted")
        payload = driver.fetch_payload()
        report = inspect_csv(payload.text) if payload.text else None
        record(
            "proj-season-2019",
            f"{report.rows if report else 0} rows, columns={len(report.columns) if report else 0}, "
            f"avg_type column present={'avg_type' in (report.columns if report else ())}",
        )

        print("\n-- dropdown bounds --")
        options = page.evaluate(
            # `el.options` holds ONLY the currently selected value -- selectize moves the
            # rest into its own store, so reading the DOM select reports a one-item list for
            # every dropdown on the page.
            """
            (id) => {
              const el = document.getElementById(id);
              if (!el || !el.selectize) return null;
              return Object.keys(el.selectize.options);
            }
            """,
            WEEK_INPUT,
        )
        record("week-options-for-2019", str(options))
        driver.set_input(YEAR_INPUT, "2026", driver.settles.after_year)
        options_2026 = page.evaluate(
            # `el.options` holds ONLY the currently selected value -- selectize moves the
            # rest into its own store, so reading the DOM select reports a one-item list for
            # every dropdown on the page.
            """
            (id) => {
              const el = document.getElementById(id);
              if (!el || !el.selectize) return null;
              return Object.keys(el.selectize.options);
            }
            """,
            WEEK_INPUT,
        )
        record("week-options-for-2026", str(options_2026))

        context.close()

    print("\n== probe summary ==")
    for name, verdict in findings:
        print(f"{name}: {verdict}")
    return 0


# ---------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    data_dir: Path = args.data_dir
    manifest_path = data_dir / MANIFEST_NAME
    jobs = _stage_jobs(args.stage)
    outstanding = plan(jobs, load_manifest(manifest_path), _on_disk(data_dir))
    done = len(jobs) - len(outstanding)
    queued = outstanding[: args.limit] if args.limit else outstanding

    # Report the limit SEPARATELY from what is already done. Computing "done" after the
    # truncation read `187 jobs, 181 already done` against an empty corpus, which is the
    # kind of line somebody believes.
    print(f"stage {args.stage}: {len(jobs)} jobs, {done} already done, "
          f"{len(outstanding)} outstanding")
    if args.limit and len(queued) < len(outstanding):
        print(f"  --limit {args.limit}: fetching {len(queued)} of them this run")
    if not queued:
        print("nothing to do")
        return 0
    if args.dry_run:
        for job in queued:
            print(f"  {job.filename}")
        return 0

    settles = Settles().scaled(args.slow) if args.slow != 1.0 else Settles()
    started = time.time()
    with sync_playwright() as pw:
        context = open_context(pw, args.profile, headless=args.headless)
        page = context.pages[0] if context.pages else context.new_page()
        driver = ShinyDriver(page, settles)
        driver.establish()
        try:
            result = run_jobs(
                driver, queued, data_dir=data_dir, manifest_path=manifest_path, now=_now
            )
        finally:
            context.close()

    minutes = (time.time() - started) / 60.0
    print(f"\ncompleted {len(result.completed)}/{result.attempted} in {minutes:.1f}m, "
          f"{len(result.failed)} failed, {result.recoveries} session recoveries")
    for job, reasons in result.failed:
        print(f"  FAILED {job.filename}: {'; '.join(reasons)}")
    return 0 if not result.failed else 1


# ---------------------------------------------------------------------------------------
# status -- G8 coverage, gaps named rather than substituted
# ---------------------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    manifest_path = data_dir / MANIFEST_NAME
    entries = load_manifest(manifest_path)
    on_disk = _on_disk(data_dir)

    print(f"manifest: {manifest_path} ({len(entries)} entries)")
    print(f"on disk:  {len(on_disk)} files, "
          f"{sum(on_disk.values()) / 1_048_576:.1f} MiB\n")

    for stage in STAGE_ORDER:
        jobs = STAGES[stage]
        missing = plan(jobs, entries, on_disk)
        print(f"{stage}: {len(jobs) - len(missing)}/{len(jobs)}")
        if missing and args.gaps:
            by_year: dict[int, list[str]] = {}
            for job in missing:
                by_year.setdefault(job.year, []).append(f"wk{job.week}:{job.avg}")
            for year in sorted(by_year):
                print(f"    {year}: {' '.join(sorted(set(by_year[year])))}")

    orphans = sorted(set(on_disk) - set(entries))
    if orphans:
        print(f"\nUNVOUCHED files on disk with no manifest entry ({len(orphans)}):")
        for name in orphans:
            print(f"    {name}")

    stale = sorted(name for name in entries if name not in on_disk)
    if stale:
        print(f"\nmanifest entries with no file ({len(stale)}):")
        for name in stale:
            print(f"    {name}")

    mislabelled = []
    for name, entry in sorted(entries.items()):
        if entry.kind == "raw" and entry.measured_avg_type != entry.avg:
            mislabelled.append(f"{name}: holds {entry.measured_avg_type}")
    print(f"\nraw files whose fifth column disagrees with their name: {len(mislabelled)}")
    for line in mislabelled:
        print(f"    {line}")

    # IDP is a property of the SCOPE. Measured: 2015 weekly carries none. Reporting it is
    # what keeps a downstream reader from assuming every file has it -- the alternative was
    # rejecting good offensive data over a position group the app does not project.
    without_idp = sorted(
        name for name, entry in entries.items()
        if not set(entry.positions) >= IDP_POSITIONS
    )
    print(f"\nfiles with no IDP ({len(without_idp)} of {len(entries)}):")
    scopes: dict[tuple[int, str], list[int]] = {}
    for name in without_idp:
        entry = entries[name]
        scopes.setdefault((entry.year, entry.kind), []).append(entry.week)
    for (year, kind), weeks in sorted(scopes.items()):
        print(f"    {year} {kind}: wk{min(weeks)}-wk{max(weeks)} ({len(weeks)} files)")

    if args.rows:
        print("\nrow counts by year and week:")
        for name, entry in sorted(entries.items()):
            print(f"    {name}: {entry.rows} rows, "
                  f"{len(entry.positions)} positions, {entry.bytes} bytes")

    if args.rehash:
        print("\nrehashing every file against the manifest...")
        from .manifest import sha256_of

        bad = []
        for name, entry in sorted(entries.items()):
            path = data_dir / name
            if not path.exists():
                continue
            if sha256_of(path.read_text(encoding="utf-8")) != entry.sha256:
                bad.append(name)
        print(f"sha256 mismatches: {len(bad)}")
        for name in bad:
            print(f"    {name}")

    if args.write_coverage:
        out = data_dir / "COVERAGE.md"
        out.write_text(_coverage_markdown(entries, data_dir), encoding="utf-8")
        print(f"\nwrote {out} ({len(entries)} files)")

    unnameable = [n for n in on_disk if not _parses(n)]
    if unnameable:
        print(f"\nfiles whose names this tool never emitted ({len(unnameable)}):")
        for name in unnameable:
            print(f"    {name}")
    return 0


def _thin_weeks(entries: dict) -> dict[tuple[int, str, str], list[int]]:
    """Weeks whose row count is under 60% of the deepest week in the same season.

    AGAINST THE SEASON MAX, NOT ITS MEDIAN. In 2017 the thin weeks are the MAJORITY -- nine
    of seventeen -- so they drag the median down to 673 and hide themselves entirely. The
    max is stable however many weeks are affected.

    This is a flag, not a verdict. 2020 runs 587-738 rows all season with IDP throughout: a
    smaller season, not a damaged one, and the median test would have misfiled it.
    """
    seasons: dict[tuple[int, str, str], list] = {}
    for entry in entries.values():
        if entry.week == 0:
            continue
        seasons.setdefault((entry.year, entry.kind, entry.avg), []).append(entry)
    thin: dict[tuple[int, str, str], list[int]] = {}
    for key, group in seasons.items():
        deepest = max(e.rows for e in group)
        weeks = sorted(e.week for e in group if e.rows < 0.6 * deepest)
        if weeks:
            thin[key] = weeks
    return thin


def _coverage_markdown(entries: dict, data_dir: Path) -> str:
    """The committed coverage artifact, regenerated from the manifest.

    GAPS ARE NAMED. A report that rounds a hole down to a percentage is how a reader ends up
    believing a season is complete when four of its weeks are not there, and this corpus
    exists because a previous one was believed rather than checked.
    """
    total_bytes = sum(e.bytes for e in entries.values())
    lines = [
        "# Coverage",
        "",
        "Regenerated by `uv run python -m sim.tools.ffa_scrape status --write-coverage`.",
        "Do not hand-edit: every number here is derived from `manifest.jsonl`.",
        "",
        f"{len(entries)} files, {total_bytes / 1_048_576:.1f} MiB.",
        "",
    ]

    on_disk = _on_disk(data_dir)
    for stage in STAGE_ORDER:
        jobs = STAGES[stage]
        missing = plan(jobs, entries, on_disk)
        lines += [f"## {stage} — {len(jobs) - len(missing)}/{len(jobs)}", ""]
        if not missing:
            lines += ["Complete.", ""]
            continue
        # Sorted on (week, avg), not on the rendered string -- lexicographic order puts
        # wk10 before wk1 and makes a gap list unreadable at exactly the moment somebody is
        # trying to read it.
        by_year: dict[int, set[tuple[int, str]]] = {}
        for job in missing:
            by_year.setdefault(job.year, set()).add((job.week, job.avg))
        lines += ["MISSING, named rather than summarised:", "", "```"]
        for year in sorted(by_year):
            rendered = " ".join(f"wk{w}:{a}" for w, a in sorted(by_year[year]))
            lines.append(f"{year}: {rendered}")
        lines += ["```", ""]

    lines += [
        "## Depth and IDP, per season",
        "",
        "`thin` is a week under 60% of the deepest week in its own season. It is a flag for",
        "a reader, not a verdict on the file: every file here passed verification, and a",
        "thin week is a complete document with fewer players in it.",
        "",
        "```",
        "year  n   min  median   max  IDP weeks        thin weeks",
    ]
    thin = _thin_weeks(entries)
    seasons: dict[int, list] = {}
    for entry in entries.values():
        if entry.week:
            seasons.setdefault(entry.year, []).append(entry)
    for year in sorted(seasons):
        group = seasons[year]
        counts = sorted(e.rows for e in group)
        median = counts[len(counts) // 2]
        with_idp = sum(1 for e in group if set(e.positions) >= IDP_POSITIONS)
        flagged = sorted({w for (y, _k, _a), ws in thin.items() if y == year for w in ws})
        lines.append(
            f"{year} {len(group):>3} {min(counts):>5} {median:>6} {max(counts):>6}  "
            f"{with_idp}/{len(group):<14} {flagged if flagged else ''}"
        )
    lines += ["```", ""]

    without = sorted(n for n, e in entries.items() if not set(e.positions) >= IDP_POSITIONS)
    lines += [
        "## IDP",
        "",
        "IDP is a property of the WEEK, not of the season, and there is no boundary year.",
        "In 2016 and 2017 the IDP-less weeks are exactly the thin ones: the source that",
        "supplied IDP supplied the offensive depth too, and both went at once. 2015 is a",
        "different shape — no IDP in any week, but full offensive depth throughout.",
        "",
        f"Files without IDP: {len(without)} of {len(entries)}.",
        "",
    ]
    if without:
        scopes: dict[tuple[int, str], list[int]] = {}
        for name in without:
            entry = entries[name]
            scopes.setdefault((entry.year, entry.kind), []).append(entry.week)
        lines.append("```")
        for (year, kind), weeks in sorted(scopes.items()):
            lines.append(f"{year} {kind}: weeks {sorted(weeks)}")
        lines += ["```", ""]

    unverifiable = [n for n, e in entries.items() if e.kind == "proj"]
    lines += [
        "## Unverifiable by construction",
        "",
        f"{len(unverifiable)} `proj` files. A proj export carries no `avg_type` column, so",
        "the aggregation it was fetched under cannot be confirmed from its own bytes. Their",
        "`measured_avg_type` is null in the manifest rather than an echo of the request.",
        "",
        "## Every file",
        "",
        "```",
    ]
    for name, entry in sorted(entries.items()):
        idp = "IDP" if set(entry.positions) >= IDP_POSITIONS else "no-IDP"
        lines.append(
            f"{name}  {entry.rows:>5} rows  {len(entry.positions)} pos  {idp:>6}  "
            f"avg_type={entry.measured_avg_type}"
        )
    lines += ["```", ""]
    return "\n".join(lines)


def _parses(name: str) -> bool:
    try:
        parse_filename(name)
    except Exception:  # noqa: BLE001 -- any failure to parse is the answer
        return False
    return True


# ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sim.tools.ffa_scrape", description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="headed sign-in; the human types the password")
    login.add_argument("--wait", type=float, default=600.0)
    login.set_defaults(func=cmd_login)

    probe = sub.add_parser("probe", help="re-measure the five behaviours")
    probe.add_argument("--headed", dest="headless", action="store_false", default=True)
    probe.set_defaults(func=cmd_probe)

    run = sub.add_parser("run", help="fetch a stage")
    run.add_argument("--stage", choices=[*STAGE_ORDER, "all"], required=True)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--slow", type=float, default=1.0, help="scale every settle")
    run.add_argument("--headed", dest="headless", action="store_false", default=True)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="coverage and gaps")
    status.add_argument("--gaps", action="store_true", help="name every missing file")
    status.add_argument("--rehash", action="store_true", help="re-verify every sha256")
    status.add_argument("--rows", action="store_true", help="per-file row counts")
    status.add_argument(
        "--write-coverage", action="store_true", help="regenerate COVERAGE.md"
    )
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
