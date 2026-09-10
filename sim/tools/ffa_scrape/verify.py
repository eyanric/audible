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

# The chart's Position dropdown filters the CHART only -- a download always carries every
# position the app HAS for that scope, which is what makes a completeness check meaningful.
NINE_POSITIONS: Final[frozenset[str]] = frozenset(
    {"QB", "RB", "WR", "TE", "K", "DST", "DL", "LB", "DB"}
)

# REQUIRED EVERYWHERE. Measured present in every scope fetched: season 2018-2026 and weekly
# 2015-2025. A file missing one of these is a defective download.
CORE_POSITIONS: Final[frozenset[str]] = frozenset({"QB", "RB", "WR", "TE", "K", "DST"})

# RECORDED, NOT REQUIRED. Measured ABSENT from early weekly files -- 2015 week 1 carries
# only the six above, and rejecting it would throw away good offensive data over a position
# group the app simply does not project for that scope. The handoff's "downloads always
# carry all nine" was verified on a SEASON file in 2019 and does not generalise to weekly.
#
# So IDP presence goes in the manifest and into the coverage report, where a downstream
# reader can see exactly which files have it, rather than being silently assumed.
IDP_POSITIONS: Final[frozenset[str]] = frozenset({"DL", "LB", "DB"})

# Structural, not incidental. `avg_type` sits at index 4 in every raw export measured. If
# FFA reorders, the read-by-name below still works and this check still fires -- which is
# what we want, because a schema change is a reason to stop, not to carry on quietly.
AVG_TYPE_INDEX: Final[int] = 4
AVG_TYPE_COLUMN: Final[str] = "avg_type"

KNOWN_KINDS: Final[frozenset[str]] = frozenset({"raw", "proj"})

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


# A raw export names its own scope in its last two columns. MEASURED over 213 raw files:
# 194 carry a populated `season_year` and `week` that agree with the filename exactly, 0
# disagree, and 19 -- 2015 and early-2016 weekly -- hold 'NA' in both.
#
# Checking them closes a hole of exactly the same shape as the one this tool exists for,
# on a different axis. If a year change has not reached the download handler, the payload
# is the PREVIOUS year's; and because a real year change also resets the aggregation to
# weighted, the stale payload and the wanted one both read `weighted`, so the avg_type
# check cannot see it. Positions are complete in both and both clear the row floor, so
# nothing else fires either.
SCOPE_COLUMNS: Final[tuple[str, str]] = ("season_year", "week")
_ABSENT: Final[frozenset[str]] = frozenset({"NA", "", "N/A", "null"})


@dataclass(frozen=True)
class FileReport:
    """What a payload actually contains, measured."""

    columns: tuple[str, ...]
    rows: int
    positions: Mapping[str, int]
    avg_types: frozenset[str]
    ragged: int
    # The distinct populated values of `season_year` and `week`, or an empty set when the
    # column is absent or holds only NA. Presence-conditional, like IDP.
    season_years: frozenset[str] = frozenset()
    weeks: frozenset[str] = frozenset()

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
    year_index = header.index(SCOPE_COLUMNS[0]) if SCOPE_COLUMNS[0] in header else None
    week_index = header.index(SCOPE_COLUMNS[1]) if SCOPE_COLUMNS[1] in header else None

    positions: dict[str, int] = {}
    avg_types: set[str] = set()
    season_years: set[str] = set()
    weeks: set[str] = set()
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
        if year_index is not None and row[year_index] not in _ABSENT:
            season_years.add(row[year_index])
        if week_index is not None and row[week_index] not in _ABSENT:
            weeks.add(row[week_index])
    return FileReport(
        columns=tuple(header),
        rows=rows,
        positions=positions,
        avg_types=frozenset(avg_types),
        ragged=ragged,
        season_years=frozenset(season_years),
        weeks=frozenset(weeks),
    )


def min_rows_for(kind: str, week: int) -> int:
    """The floor for this scope.

    NOT a scope discriminator, and the docstring here used to claim otherwise -- "season
    files are far larger than weekly ones". MEASURED over 213 files: season raw spans
    819..2236 rows and weekly raw spans 521..1856, and 113 of 186 weekly files hold more
    rows than the smallest season file. The ranges overlap almost entirely.

    That matters because a reader who believes the floors separate season from weekly does
    not add the check that actually does, which is `season_year`/`week` in the payload
    itself. These floors catch a stub, an error page or an empty frame. Nothing more.
    """
    return _MIN_ROWS[(kind, week == 0)]


def verify_payload(
    text: str,
    *,
    kind: str,
    year: int,
    week: int,
    avg: str,
    min_rows: int | None = None,
) -> list[str]:
    """Every reason this payload is not what was asked for. Empty list means keep it.

    A caller must treat a non-empty list as fatal for that file. There is no severity here
    on purpose: the prior attempt survived precisely because a mismatch looked survivable.
    """
    reasons: list[str] = []
    # BEFORE the row floor, which indexes on `kind` and would raise on an unknown one. The
    # unknown-kind reason used to sit below it and was unreachable on every production call
    # path: min_rows_for raised KeyError first, so a typo'd kind killed the run with a
    # traceback out of run_jobs instead of rejecting one file with a logged reason. That
    # contradicted this module's own contract -- every check returns a reason, none raise.
    if kind not in KNOWN_KINDS:
        return [f"unknown-kind: {kind!r}"]
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

    present = set(report.positions)
    missing = CORE_POSITIONS - present
    if missing:
        reasons.append(
            f"positions-missing: {sorted(missing)} absent "
            f"(have {sorted(report.positions)})"
        )
    # All-or-nothing. A scope either has IDP or it does not; a file with two of the three is
    # not a narrower file, it is a broken one.
    idp = IDP_POSITIONS & present
    if idp and idp != IDP_POSITIONS:
        reasons.append(
            f"positions-partial-idp: {sorted(idp)} present but "
            f"{sorted(IDP_POSITIONS - present)} absent"
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
    elif kind == "proj" and AVG_TYPE_COLUMN in report.columns:
        reasons.append(
            "avg-type-column-unexpected: a proj file gained an aggregation column; "
            "the unverifiable-by-construction assumption no longer holds"
        )

    # THE SCOPE CHECK. Presence-conditional, like IDP: 19 of 213 raw files hold 'NA' in
    # both columns and are not defective for it. Where the payload DOES name its own
    # season and week, it must be the one that was asked for.
    if report.season_years and report.season_years != frozenset({str(year)}):
        reasons.append(
            f"season-mismatch: asked for {year}, file holds "
            f"{sorted(report.season_years)} -- the year change had not reached the "
            "download handler"
        )
    if report.weeks and report.weeks != frozenset({str(week)}):
        reasons.append(
            f"week-mismatch: asked for wk{week}, file holds "
            f"{sorted(report.weeks)} -- the week change had not reached the download handler"
        )

    return reasons
