"""Drive the jobs: prepare, fetch, verify, write, record. In that order, every time.

WRITE ONLY WHAT VERIFIED. The payload is verified in memory and reaches disk only if it has
no reasons against it, so a file that FAILED is never written at all.

The file lands before its manifest line, which means a kill in the microseconds between
them leaves a file with no entry -- NOT "a corpus can never contain a file the manifest
does not vouch for", which is what this docstring used to claim. That window is the safe
direction to fail: `plan` re-fetches a file the manifest does not name, and `status`
reports it as UNVOUCHED. The reverse order would leave an entry vouching for bytes that
are not there.

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

# A DROPPED SESSION DOES NOT ALWAYS ARRIVE AS SessionLost. It also arrives as whatever
# Playwright raises when the page it is driving goes away mid-call -- and that used to
# escape run_jobs and kill the whole run. Measured: a Shiny modal intercepted a tab click
# and the resulting TimeoutError ended stage 2 eight files in, with seven good files on
# disk and nothing to say why.
#
# Matched by NAME rather than by importing playwright, so this module stays importable
# without it and a gate can raise the same shapes without a browser. NotLoggedIn is
# deliberately NOT here: it is the one failure a human has to fix, and retrying it 600
# times against someone else's server is the opposite of helpful.
RECOVERABLE_NAMES = frozenset({"TimeoutError", "Error", "TargetClosedError"})


def is_recoverable(exc: BaseException) -> bool:
    """Is this a lost session wearing someone else's exception type?

    CHECKED AFTER THE CATCH, NEVER IN THE except CLAUSE. The first version of this was a
    class with a metaclass `__instancecheck__` matching on `__name__`, used as
    `except (SessionLost, Recoverable)`. It was INERT: CPython matches except clauses
    through PyType_IsSubtype, which never consults `__instancecheck__` -- the same reason
    an ABC virtual subclass cannot be caught. `isinstance(exc, Recoverable)` answered True
    while the except clause let the exception straight through, so the guard silently
    reverted to `except SessionLost` and the defect it was written to fix was still there.

    No gate caught that, because every session-loss gate injects SessionLost, which matches
    by real subtyping and exercises only the half that worked.
    """
    return isinstance(exc, SessionLost) or type(exc).__name__ in RECOVERABLE_NAMES


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


def _reject(result: object, text: str) -> list[str]:
    """Reasons a payload never even reaches the CSV checks."""
    if not getattr(result, "ok", False):
        status = getattr(result, "status", 0)
        error = getattr(result, "error", "")
        return [f"fetch-failed: status {status} {error}".strip()]
    if _looks_like_html(text):
        # A logged-out session serves the login page with a 200. It is not a CSV and it is
        # not an error the browser reports.
        return [f"html-payload: {len(text)} bytes of HTML, not CSV"]
    return []


def _attempt(
    driver: ShinyDriver,
    job: Job,
    *,
    scale: float,
) -> tuple[str | None, list[str], str | None]:
    """One attempt.

    Returns (payload, reasons, witness_sha). A payload only when reasons is empty; a witness
    only for `proj` jobs, where it is the sha256 of the raw file that vouched for the
    aggregation.
    """
    original = driver.settles
    try:
        if scale != 1.0:
            driver.settles = original.scaled(scale)
        # The retry is strictly stronger than the first attempt, not merely
        # slower: it also forces the Settings trip the first attempt may have
        # judged unnecessary. A wrong aggregation is the failure this retry
        # exists for, so the retry must not repeat the judgement that caused it.
        #
        # A `proj` job is prepared as `raw` FIRST. A proj export carries no avg_type
        # column, so alone it cannot say which aggregation produced it -- fetch the raw
        # file from the same session state, read its fifth column, and the aggregation is
        # witnessed. The proj fetch that follows differs in exactly one input.
        witness_sha: str | None = None
        driver.prepare(
            "raw" if job.kind == "proj" else job.kind,
            job.year,
            job.week,
            job.avg,
            force_settings_trip=scale != 1.0,
        )
        if job.kind == "proj":
            witness = driver.fetch_payload()
            reasons = _reject(witness, witness.text)
            if reasons:
                return None, [f"witness-{r}" for r in reasons], None
            reasons = verify_payload(
                witness.text, kind="raw", year=job.year, week=job.week, avg=job.avg
            )
            if reasons:
                return None, [f"witness-{r}" for r in reasons], None
            witness_sha = sha256_of(witness.text)
            driver.switch_kind("proj", job.year, job.week)
        result = driver.fetch_payload()
    finally:
        driver.settles = original

    reasons = _reject(result, result.text)
    if reasons:
        return None, reasons, None

    reasons = verify_payload(
        result.text, kind=job.kind, year=job.year, week=job.week, avg=job.avg
    )
    return (result.text if not reasons else None), reasons, witness_sha


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
        witness_sha: str | None = None

        # EVERY attempt's reasons, not just the last one's. Keeping only the final attempt
        # erased an aggregation mismatch on attempt 1 whenever attempt 2 lost the session,
        # and the durable record then said "transient session loss" about a job that had
        # actually come back mislabelled -- which is the one thing this log exists to catch.
        history: list[str] = []

        for scale in (1.0, RETRY_SCALE):
            try:
                payload, reasons, witness_sha = _attempt(driver, job, scale=scale)
                # RESET ONLY ON SUCCESS. Resetting whenever an attempt merely RETURNED meant
                # an alternating loss/rejection pattern never tripped the cap -- the run
                # would hammer the server indefinitely, which is the thing the cap is for.
                if payload is not None:
                    consecutive_recoveries = 0
            except NotLoggedIn:
                raise
            except Exception as exc:
                if not is_recoverable(exc):
                    raise
                consecutive_recoveries += 1
                result.recoveries += 1
                log(f"    {type(exc).__name__} ({exc}); re-establishing "
                    f"[{consecutive_recoveries}/{MAX_CONSECUTIVE_RECOVERIES}]")
                if consecutive_recoveries > MAX_CONSECUTIVE_RECOVERIES:
                    raise
                driver.establish()
                reasons = [f"{type(exc).__name__.lower()}: {exc}"]
                history.extend(reasons)
                payload = None
                witness_sha = None
                continue
            history.extend(reasons)
            if payload is not None:
                break
            log(f"    rejected: {'; '.join(reasons)}")
            if scale == 1.0:
                log(f"    retrying with settles x{RETRY_SCALE}")

        if payload is None:
            log(f"    FAILED {job.filename}: {'; '.join(history)}")
            result.failed.append((job, history))
            _record_failure(data_dir / FAILURE_LOG, job, history, now())
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
                witness_sha256=witness_sha,
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
