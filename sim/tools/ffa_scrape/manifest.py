"""The manifest is the only durable record of what completed.

A shinyapps.io session reloads on idle or on a resource cap. The prior attempt kept its
progress in page memory, so a reload mid-flight left nothing behind saying which of the
thirty-odd jobs had actually landed. This file is appended after each SUCCESS -- never
before, never in a batch at the end -- so a kill at any instant leaves a manifest that is
true, and at worst one line short.

JSONL rather than a single JSON document for exactly that reason: appending a line cannot
corrupt the lines already written, whereas rewriting a document can, and a torn final line
from a kill mid-write is discardable rather than fatal.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

MANIFEST_NAME = "manifest.jsonl"


@dataclass(frozen=True)
class ManifestEntry:
    """One verified file. Every field a re-run needs to decide it can skip this job."""

    file: str
    kind: str
    year: int
    week: int
    avg: str
    sha256: str
    bytes: int
    rows: int
    # What the fifth column actually said. None for `proj`, which carries no such column and
    # is therefore unverifiable -- recorded as None rather than echoing `avg` back, so the
    # manifest never claims a verification that did not happen.
    measured_avg_type: str | None
    # For a `proj` file, the sha256 of the RAW file fetched from the same session state
    # immediately before it. A proj export has no avg_type column of its own, so this is
    # what stands behind its aggregation: the raw witness did carry one, and it matched.
    # None for raw files, which vouch for themselves, and None for any proj file fetched
    # before witnessing existed.
    witness_sha256: str | None
    positions: Mapping[str, int]
    fetched_at: str

    def as_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> dict[str, ManifestEntry]:
    """Filename -> entry, last write winning. A torn final line is dropped, not raised.

    Dropping it is correct: a line that did not finish being written describes a fetch whose
    success we cannot vouch for, and re-fetching one file is cheap next to guessing.
    """
    entries: dict[str, ManifestEntry] = {}
    if not path.exists():
        return entries
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                continue  # torn by a kill mid-append
            raise
        entries[payload["file"]] = ManifestEntry(
            file=payload["file"],
            kind=payload["kind"],
            year=payload["year"],
            week=payload["week"],
            avg=payload["avg"],
            sha256=payload["sha256"],
            bytes=payload["bytes"],
            rows=payload["rows"],
            measured_avg_type=payload.get("measured_avg_type"),
            witness_sha256=payload.get("witness_sha256"),
            positions=payload.get("positions", {}),
            fetched_at=payload["fetched_at"],
        )
    return entries


def append_entry(path: Path, entry: ManifestEntry) -> None:
    """Append one line and force it to disk before the caller believes the job is done.

    HEAL A TORN TAIL FIRST. `load_manifest` tolerates a half-written final line, but
    appending straight onto one CONCATENATES with it: the good new line is swallowed into
    an unparseable one, and as soon as a further line follows, that corruption is no longer
    the last line and `load_manifest` raises on it -- turning one lost file into a manifest
    that will not load at all.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        raw = path.read_bytes()
        if not raw.endswith(b"\n"):
            # DROP the partial line, do not merely terminate it. `load_manifest` discards a
            # torn tail because it describes a fetch nobody can vouch for; terminating it
            # instead would leave an unparseable line that is no longer LAST, and
            # `load_manifest` is deliberately strict about corruption anywhere else -- so
            # the next append would turn one lost file into a manifest that will not load.
            cut = raw.rfind(b"\n")
            path.write_bytes(raw[: cut + 1] if cut != -1 else b"")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(entry.as_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
