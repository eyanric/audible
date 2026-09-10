"""Drive the jobs: prepare, fetch, verify, write, record. In that order, every time.

WRITE ONLY WHAT VERIFIED. The payload is verified in memory and reaches disk only if it has
no reasons against it. A file that fails is never written, so a corpus directory can never
contain a file the manifest does not vouch for -- which is what makes `plan`'s
manifest-and-disk rule sound.

RETRY ONCE, LONGER, THEN GIVE UP LOUDLY. The most likely cause of an aggregation mismatch is
a settle that was too short under load, so the retry scales every wait. The second most
likely cause is that the app changed, and no number of retries fixes that. Two attempts, then
the job is recorded as a failure and the run moves on -- a run that stops dead on one bad file
leaves 600 good ones unfetched.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .driver import RETRY_SCALE, NotLoggedIn, SessionLost, ShinyDriver
from .jobs import Job
from .manifest import ManifestEntry, append_entry, sha256_of
from .verify import inspect_csv, verify_payload

FAILURE_LOG = "failures.jsonl"

# A run that keeps losing its session is not making progress, it is hammering someone else's
# server. Consecutive, so a long clean run resets it.
MAX_CONSECUTIVE_RECOVERIES = 5


@dataclass
class RunResult:
    completed: list[str] = field(default_factory=list)
    failed: list[tuple[Job, list[str]]] = field(default_factory=list)
    recoveries: int = 0
    attempted: int = 0


def write_payload(data_dir: Path, name: str, text: str) -> int:
    """Write via `.part` + rename, so a kill mid-write cannot leave a plausible file.

    Bytes, not text: writing str on Windows would translate the payload's \\n to \\r\\n and
    the file on disk would no longer hash to the sha256 the manifest records.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8")
    part = data_dir / (name + ".part")
    part.write_bytes(payload)
    os.replace(part, data_dir / name)
    return len(payload)


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:400].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _attempt(
    driver: ShinyDriver,
    job: Job,
    *,
    scale: float,
) -> tuple[str | None, list[str]]:
    """One attempt. Returns (payload, reasons) -- a payload only when reasons is empty."""
    original = driver.settles
    try:
        if scale != 1.0:
            driver.settles = original.scaled(scale)
        # The retry is strictly stronger than the first attempt, not merely
        # slower: it also forces the Settings trip the first attempt may have
        # judged unnecessary. A wrong aggregation is the failure this retry
        # exists for, so the retry must not repeat the judgement that caused it.
        driver.prepare(
            job.kind, job.year, job.week, job.avg,
            force_settings_trip=scale != 1.0,
        )
        result = driver.fetch_payload()
    finally:
        driver.settles = original

    if not result.ok:
        return None, [f"fetch-failed: status {result.status} {result.error}".strip()]
    if _looks_like_html(result.text):
        # A logged-out session serves the login page with a 200. It is not a CSV and it is
        # not an error the browser reports.
        return None, [f"html-payload: {len(result.text)} bytes of HTML, not CSV"]

    reasons = verify_payload(result.text, kind=job.kind, week=job.week, avg=job.avg)
    return (result.text if not reasons else None), reasons


def run_jobs(
    driver: ShinyDriver,
    jobs: Sequence[Job],
    *,
    data_dir: Path,
    manifest_path: Path,
    now: Callable[[], str],
    log: Callable[[str], None] = print,
    on_progress: Callable[[int, int, Job], None] | None = None,
) -> RunResult:
    result = RunResult()
    consecutive_recoveries = 0
    total = len(jobs)

    for index, job in enumerate(jobs, start=1):
        if on_progress is not None:
            on_progress(index, total, job)
        log(f"[{index}/{total}] {job.filename}")
        result.attempted += 1
        reasons: list[str] = []
        payload: str | None = None

        for scale in (1.0, RETRY_SCALE):
            try:
                payload, reasons = _attempt(driver, job, scale=scale)
                consecutive_recoveries = 0
            except SessionLost as exc:
                consecutive_recoveries += 1
                result.recoveries += 1
                log(f"    session lost ({exc}); re-establishing "
                    f"[{consecutive_recoveries}/{MAX_CONSECUTIVE_RECOVERIES}]")
                if consecutive_recoveries > MAX_CONSECUTIVE_RECOVERIES:
                    raise
                driver.establish()
                reasons = [f"session-lost: {exc}"]
                payload = None
                continue
            except NotLoggedIn:
                raise
            if payload is not None:
                break
            log(f"    rejected: {'; '.join(reasons)}")
            if scale == 1.0:
                log(f"    retrying with settles x{RETRY_SCALE}")

        if payload is None:
            log(f"    FAILED {job.filename}: {'; '.join(reasons)}")
            result.failed.append((job, reasons))
            _record_failure(data_dir / FAILURE_LOG, job, reasons, now())
            continue

        report = inspect_csv(payload)
        size = write_payload(data_dir, job.filename, payload)
        append_entry(
            manifest_path,
            ManifestEntry(
                file=job.filename,
                kind=job.kind,
                year=job.year,
                week=job.week,
                avg=job.avg,
                sha256=sha256_of(payload),
                bytes=size,
                rows=report.rows,
                measured_avg_type=report.sole_avg_type,
                positions=dict(sorted(report.positions.items())),
                fetched_at=now(),
            ),
        )
        result.completed.append(job.filename)
        log(f"    ok {report.rows} rows, {size} bytes, avg_type={report.sole_avg_type}")

    return result


def _record_failure(path: Path, job: Job, reasons: Iterable[str], when: str) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "file": job.filename,
            "kind": job.kind,
            "year": job.year,
            "week": job.week,
            "avg": job.avg,
            "reasons": list(reasons),
            "at": when,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
