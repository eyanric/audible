"""Deterministic filenames, and their inverse.

The filename is the ONLY label a file on disk carries -- a raw CSV names its aggregation
nowhere in its own bytes except the fifth column, and a `proj` CSV names it nowhere at all.
So the name has to be constructed, never chosen by a browser, and it has to round-trip: a
corpus is reconciled against a job list by parsing names back into jobs.

Chrome's `(1)`/`(2)` suffixing is what made the prior attempt unrecoverable. Nothing here
can produce a suffix, and `parse_filename` rejects one rather than silently reading
`ffa_raw_2019_wk0_average (1).csv` as a clean `average`.
"""

from __future__ import annotations

import re

KINDS: tuple[str, ...] = ("raw", "proj")
AVG_TYPES: tuple[str, ...] = ("weighted", "average", "robust")

# The app's own bounds, from the year and week dropdowns. Weekly exists only from 2015;
# `jobs.py` holds that rule because it is about which jobs are legal, not which names are.
MIN_YEAR = 2008
MAX_YEAR = 2026
MIN_WEEK = 0
MAX_WEEK = 21

_PATTERN = re.compile(
    r"^ffa_(?P<kind>raw|proj)_(?P<year>\d{4})_wk(?P<week>\d{1,2})_"
    r"(?P<avg>weighted|average|robust)\.csv$"
)


class NamingError(ValueError):
    """A job that cannot be named, or a name that cannot be parsed."""


def filename(kind: str, year: int, week: int, avg: str) -> str:
    """`ffa_{kind}_{year}_wk{week}_{avg}.csv`, or raise.

    Validation is here rather than at the call site so that a typo cannot reach disk as a
    plausible-looking name. A file named `ffa_raw_2019_wk0_mean.csv` would sit in the corpus
    forever looking like a fourth aggregation.
    """
    if kind not in KINDS:
        raise NamingError(f"kind must be one of {KINDS}, got {kind!r}")
    if avg not in AVG_TYPES:
        raise NamingError(f"avg must be one of {AVG_TYPES}, got {avg!r}")
    if not isinstance(year, int) or isinstance(year, bool):
        raise NamingError(f"year must be an int, got {year!r}")
    if not isinstance(week, int) or isinstance(week, bool):
        raise NamingError(f"week must be an int, got {week!r}")
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise NamingError(f"year {year} outside {MIN_YEAR}..{MAX_YEAR}")
    if not MIN_WEEK <= week <= MAX_WEEK:
        raise NamingError(f"week {week} outside {MIN_WEEK}..{MAX_WEEK}")
    return f"ffa_{kind}_{year}_wk{week}_{avg}.csv"


def parse_filename(name: str) -> tuple[str, int, int, str]:
    """Inverse of `filename`. Raises on anything it did not produce."""
    match = _PATTERN.match(name)
    if match is None:
        raise NamingError(f"not a corpus filename: {name!r}")
    kind = match.group("kind")
    year = int(match.group("year"))
    week = int(match.group("week"))
    avg = match.group("avg")
    # Round-trip rather than trust the regex: `wk007` matches \d{1,2}? No -- but `wk00`
    # does, and would parse to week 0 under a name `filename` never emits.
    if filename(kind, year, week, avg) != name:
        raise NamingError(f"name does not round-trip: {name!r}")
    return kind, year, week, avg
