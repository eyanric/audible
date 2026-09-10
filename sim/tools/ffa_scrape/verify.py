"""Verify a payload against the job that asked for it, BEFORE it is written.

This module is the whole reason the tool exists. The prior attempt's 36 mislabelled files
were not detected by anything until a human read a fifth column by hand; by then the names
were already wrong on disk and Chrome's `(1)` suffixing had put the contaminated copy under
the clean name.

WHAT SELF-VERIFIES AND WHAT DOES NOT. `avg_type` is the fifth column of every `raw` file, so
a raw download carries its own aggregation label and can be checked against what was
requested. A `proj` file has no such column -- measured on the nine season exports already on
disk, whose 22 columns are `player, position, team, bye_week, points, ...`. A `proj` file's
aggregation is therefore UNVERIFIABLE and is recorded as such rather than assumed correct.
That is why the corpus prefers `raw`.

Every check returns a REASON rather than raising, so a caller can log all of them at once and
so a test can assert on which one fired. A payload with any reason is never written.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

# Measured on 2019: QB 158, RB 291, WR 422, TE 218, K 57, DST 33, DL 351, LB 309, DB 399,
# 2238 rows. The chart's Position dropdown filters the CHART only -- a download always
# carries all nine, which is what makes the completeness check meaningful.
NINE_POSITIONS: Final[frozenset[str]] = frozenset(
    {"QB", "RB", "WR", "TE", "K", "DST", "DL", "LB", "DB"}
)

# Structural, not incidental. `avg_type` sits at index 4 in every raw export measured. If
# FFA reorders, the read-by-name below still works and this check still fires -- which is
# what we want, because a schema change is a reason to stop, not to carry on quietly.
AVG_TYPE_INDEX: Final[int] = 4
AVG_TYPE_COLUMN: Final[str] = "avg_type"

# Floors that catch truncation, not tight bounds. Real counts range 830..2238 for season raw
# and 493..593 for season proj, and vary by how deep FFA's sources went that year, so a tight
# bound would reject good files. `_ragged` is the precise truncation check; these catch a
# response that came back as a stub, an error page, or an empty frame.
_MIN_ROWS: Final[Mapping[tuple[str, bool], int]] = {
    ("raw", True): 400,  # season
    ("proj", True): 200,
    ("raw", False): 120,  # weekly
    ("proj", False): 80,
}


@dataclass(frozen=True)
class FileReport:
    """What a payload actually contains, measured."""

    columns: tuple[str, ...]
    rows: int
    positions: Mapping[str, int]
    avg_types: frozenset[str]
    ragged: int

    @property
    def sole_avg_type(self) -> str | None:
        """The one aggregation in the file, or None if absent or mixed."""
        if len(self.avg_types) == 1:
            return next(iter(self.avg_types))
        return None


class EmptyPayload(ValueError):
    """A payload with no header at all. Distinct from a payload that merely fails checks."""


def inspect_csv(text: str) -> FileReport:
    """Measure a payload. Never judges it -- `verify_payload` does that."""
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise EmptyPayload("payload has no header row") from exc
    if not header:
        raise EmptyPayload("payload header row is empty")

    pos_index = header.index("position") if "position" in header else None
    avg_index = header.index(AVG_TYPE_COLUMN) if AVG_TYPE_COLUMN in header else None

    positions: dict[str, int] = {}
    avg_types: set[str] = set()
    rows = 0
    ragged = 0
    width = len(header)
    for row in reader:
        if not row:
            continue  # a trailing newline is not a row
        rows += 1
        if len(row) != width:
            ragged += 1
            continue  # a torn row's fields are not trustworthy at any index
        if pos_index is not None:
            positions[row[pos_index]] = positions.get(row[pos_index], 0) + 1
        if avg_index is not None:
            avg_types.add(row[avg_index])
    return FileReport(
        columns=tuple(header),
        rows=rows,
        positions=positions,
        avg_types=frozenset(avg_types),
        ragged=ragged,
    )


def min_rows_for(kind: str, week: int) -> int:
    """The floor for this scope. Season (week 0) files are far larger than weekly ones."""
    return _MIN_ROWS[(kind, week == 0)]


def verify_payload(
    text: str,
    *,
    kind: str,
    week: int,
    avg: str,
    min_rows: int | None = None,
) -> list[str]:
    """Every reason this payload is not what was asked for. Empty list means keep it.

    A caller must treat a non-empty list as fatal for that file. There is no severity here
    on purpose: the prior attempt survived precisely because a mismatch looked survivable.
    """
    reasons: list[str] = []
    try:
        report = inspect_csv(text)
    except EmptyPayload as exc:
        return [f"empty-payload: {exc}"]

    if report.ragged:
        reasons.append(
            f"ragged-rows: {report.ragged} row(s) do not have {len(report.columns)} fields "
            "-- the payload is truncated or the schema changed mid-file"
        )

    floor = min_rows_for(kind, week) if min_rows is None else min_rows
    if report.rows < floor:
        reasons.append(
            f"row-count: {report.rows} rows is below the floor of {floor} "
            f"for {kind} wk{week}"
        )

    missing = NINE_POSITIONS - set(report.positions)
    if missing:
        reasons.append(
            f"positions-missing: {sorted(missing)} absent "
            f"(have {sorted(report.positions)})"
        )

    if kind == "raw":
        if AVG_TYPE_COLUMN not in report.columns:
            reasons.append(f"avg-type-column-absent: a raw file must carry {AVG_TYPE_COLUMN!r}")
        else:
            index = report.columns.index(AVG_TYPE_COLUMN)
            if index != AVG_TYPE_INDEX:
                reasons.append(
                    f"avg-type-column-moved: {AVG_TYPE_COLUMN!r} is column {index + 1}, "
                    f"expected column {AVG_TYPE_INDEX + 1}"
                )
            if report.avg_types != frozenset({avg}):
                # THE check. A `weighted` payload arriving for an `average` job is the exact
                # defect that put weighted data under two other names last time.
                reasons.append(
                    f"avg-type-mismatch: asked for {avg!r}, file holds "
                    f"{sorted(report.avg_types)} -- the year change reset the aggregation"
                )
    elif kind == "proj":
        if AVG_TYPE_COLUMN in report.columns:
            reasons.append(
                "avg-type-column-unexpected: a proj file gained an aggregation column; "
                "the unverifiable-by-construction assumption no longer holds"
            )
    else:
        reasons.append(f"unknown-kind: {kind!r}")

    return reasons
