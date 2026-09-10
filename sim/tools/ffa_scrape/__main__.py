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
from .verify import inspect_csv, verify_payload

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
        reasons = verify_payload(payload.text, kind="raw", week=0, avg="weighted")
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
            reasons = verify_payload(payload.text, kind="raw", week=0, avg=avg)
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
            reasons = verify_payload(payload.text, kind="raw", week=week, avg="weighted")
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
            """
            (id) => {
              const el = document.getElementById(id);
              if (!el) return null;
              return Array.from(el.options || []).map(o => o.value);
            }
            """,
            WEEK_INPUT,
        )
        record("week-options-for-2019", str(options))
        driver.set_input(YEAR_INPUT, "2026", driver.settles.after_year)
        options_2026 = page.evaluate(
            """
            (id) => {
              const el = document.getElementById(id);
              if (!el) return null;
              return Array.from(el.options || []).map(o => o.value);
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
    queued = plan(jobs, load_manifest(manifest_path), _on_disk(data_dir))
    if args.limit:
        queued = queued[: args.limit]

    print(f"stage {args.stage}: {len(jobs)} jobs, {len(jobs) - len(queued)} already done, "
          f"{len(queued)} queued")
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

    unnameable = [n for n in on_disk if not _parses(n)]
    if unnameable:
        print(f"\nfiles whose names this tool never emitted ({len(unnameable)}):")
        for name in unnameable:
            print(f"    {name}")
    return 0


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
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
