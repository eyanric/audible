"""The report split, and the lock that keeps it a holdout.

A holdout looked at twice is a validation set with extra steps. Two splits were enough for
`audible#84`'s four hand-written hypotheses and are dishonest for a thousand candidates: pick
the best on your test seasons and the number you report was chosen BECAUSE it looked good
there.

So the report seasons are UNREADABLE to the search until exactly one candidate has been fixed
in a committed file. Not a convention, not a comment -- `assert_unlocked` raises, and it checks
that the lock is TRACKED BY GIT rather than merely present, because an untracked file can be
written a moment before it is read and deleted a moment after.

THE ONE DECLARED EXCEPTION. `audible#84` published its headline numbers on 2024-2025, and this
session's G2 required re-reporting them under a new indexing. The report split's INCUMBENT
score is therefore already known. That is recorded in `sim/runs/s2b-search.md` rather than
hidden. What the lock protects is the thing that actually matters: no SEARCH CANDIDATE is ever
scored on these seasons until one is chosen and committed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO / "sim" / "runs" / "s2b-candidate.lock"

FIT_SEASONS: tuple[int, ...] = (2019, 2020, 2021)
SELECT_SEASONS: tuple[int, ...] = (2022, 2023)
REPORT_SEASONS: tuple[int, ...] = (2024, 2025)


class HoldoutLocked(RuntimeError):
    """Raised when the search reaches for the report split before committing a candidate."""


def candidate_hash(candidate: dict[str, Any]) -> str:
    """A stable sha256 over the candidate's knobs. Key order cannot change it."""
    blob = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _tracked(path: Path) -> bool:
    """Is *path* tracked by git? An untracked lock proves nothing about when it was written."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path.relative_to(REPO))],
            cwd=REPO, capture_output=True, text=True, timeout=30,
        )
        return out.returncode == 0
    except Exception:
        return False


def committed_candidate() -> dict[str, Any] | None:
    """The one candidate the holdout has been unlocked for, or None."""
    if not LOCK_PATH.exists() or not _tracked(LOCK_PATH):
        return None
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    stated = data.get("sha256")
    knobs = data.get("candidate")
    if not isinstance(knobs, dict) or candidate_hash(knobs) != stated:
        raise HoldoutLocked(
            f"{LOCK_PATH.name} is present but its sha256 does not match its candidate. "
            f"A lock that does not verify is not a lock."
        )
    return data


def assert_unlocked(seasons: tuple[int, ...] | list[int]) -> None:
    """Raise unless every report season requested is covered by a committed candidate."""
    touched = [s for s in seasons if s in REPORT_SEASONS]
    if not touched:
        return
    data = committed_candidate()
    if data is None:
        raise HoldoutLocked(
            f"the report split {list(REPORT_SEASONS)} is locked -- {touched} was requested "
            f"and no committed candidate exists. Write {LOCK_PATH.name} with exactly one "
            f"candidate and its sha256, `git add` it, and commit it. The holdout is spent "
            f"once and this is what makes the number at the end mean anything."
        )


def lock_candidate(candidate: dict[str, Any], note: str) -> dict[str, Any]:
    """Write the lock. Committing it is a separate, deliberate act and is NOT done here."""
    payload = {
        "candidate": candidate,
        "sha256": candidate_hash(candidate),
        "note": note,
        "report_seasons": list(REPORT_SEASONS),
    }
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return payload
