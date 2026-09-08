"""A MARKET is a league config plus an ADP source measured in that format.

WHY THIS EXISTS. Every comparison this project has run is against one market:
FantasyFootballCalculator, which serves a TWELVE-team board. `room.py:228-232` says so and the
pinned files agree -- `meta.teams` reads 12 in all five, in files whose names say 8. Both
leagues that matter here are EIGHT-team. So every gap number this harness has produced carries
an unquantified team-count confound, and the only way to size it is to run the same experiment
in a market that is actually eight-team.

The fix is not to find one better market. Audible already scores stat lines under whatever
`LeagueConfig` it is handed -- nothing in `build_board_from_lines` is tied to a format -- so
the market can stop being hardcoded. A second market is then a nearly independent test of the
same method, because the board, the market and the scoring all differ. That is a SECOND AXIS
against the five-season-cluster constraint, and it costs an adapter rather than a season.

HOW IT IS SELECTED. One module-level active market, set from the run config and readable by
`room.load_board`. A global is not the shape anyone wants, and the alternative is worse:
`fit_room` calls `load_board` itself, twice, and there are 41 call sites across sim/. Threading
a parameter through all of them would touch far more code than this, for a value that is
constant for the length of a run. `use()` is a context manager so a test can scope it, and
nothing mutates it except the runner and that manager.

WHAT IS DELIBERATELY NOT GENERALISED. The `ffc%04d` draftable-id prefix stays `ffc` for every
market. It is an internal key space meaning "board row N", it is written into every committed
artifact and checkpoint, and renaming it would invalidate every run this repo has recorded
while changing nothing about behaviour. The name is historical; the meaning is market-neutral,
and `room.DRAFTABLE_PREFIX` now says so.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Source names. These reach `room.PRE_DRAFT_SOURCES`, so a new one must be added there or
# `assert_pre_draft` refuses every board it builds -- which is the correct default: an
# unrecognised provenance is a leak until someone says otherwise.
FFC = "ffc"
MFL = "mfl"

# The START of each MFL ADP window, as a (month, day). MFL selects drafts from this date
# ONWARD and publishes no end, so these are lower bounds. `START` and `DRAFT` are deliberately
# absent: measured, they return a different top three and a different draft count, which makes
# them a different population rather than a later window.
PERIOD_STARTS: dict[str, tuple[int, int]] = {
    "JUNE": (6, 1), "JULY": (7, 1), "AUG1": (8, 1), "AUG15": (8, 15),
}


@dataclass(frozen=True, slots=True)
class Market:
    """One market: what league it is, where its ADP comes from, and how it is pinned.

    `league` is a key under `leagues/`, not a config object, so a market is declarable in a
    TOML without inlining a scoring table. `params` is source-specific and opaque here.
    """

    name: str
    league: str
    source: str
    params: dict[str, Any] = field(default_factory=dict)
    # What `SeasonBoard.provenance` carries, checked by `room.assert_pre_draft`.
    provenance: str = "ffc_adp"

    def pins(self, season: int) -> tuple[str, ...]:
        """Every file this market needs for *season*, relative to a cache root.

        `runner.required_inputs` reads this, which is what makes a missing pin fail in
        PREFLIGHT rather than half way through a sweep. A market that forgets to declare a
        file here still works on a machine that happens to have it, and fails mid-run on one
        that does not -- which is the failure mode preflight exists to prevent.
        """
        if self.source == FFC:
            return (f"ffc_adp_standard_8_{season}.json",)
        if self.source == MFL:
            from .mfl import MflParams, adp_pin, players_pin

            params = MflParams(**self.params)
            return (f"mfl/{adp_pin(season, params)}", f"mfl/{players_pin(season)}")
        raise ValueError(f"unknown ADP source {self.source!r}")

    def asof(self, season: int) -> date:
        """The date the board is claimed to be current as of.

        FFC publishes `meta.end_date` and `room.load_board` reads it. MFL PUBLISHES NOTHING OF
        THE KIND, and that is a real limitation rather than a detail: `PERIOD=AUG15` selects
        drafts from 15 August ONWARD, and MFL does not say where the window ends. The
        `timestamp` field is when the response was generated -- it reads as today on a 2019
        request -- so it is not provenance either.

        So this returns the window's START, which is a lower bound and is honest about being
        one, and the pre-draft property is established by CONTENT instead: `sim/test_g_b8.py`
        checks each season's board for the FOLLOWING year's draft class, the same way the FFA
        vintage gate does. A handful of leagues drafting after kickoff would be inside this
        window and would be a small leak; redraft leagues overwhelmingly draft in August, and
        that bound is an argument rather than a measurement.
        """
        if self.source == MFL:
            period = str(self.params.get("period", "AUG15")).strip().upper()
            if period not in PERIOD_STARTS:
                # REFUSED, NOT DEFAULTED. An earlier version fell back to 15 August for any
                # unrecognised period, which meant `PERIOD=START` -- a genuinely different and
                # partly in-season population, measured and documented as such in `sim/mfl.py`
                # -- would be stamped mid-August and sail through `room.assert_pre_draft`. A
                # date nobody measured is not a lower bound, it is a guess wearing one.
                raise ValueError(
                    f"{self.name}: PERIOD={period!r} has no measured window start. Known: "
                    f"{sorted(PERIOD_STARTS)}. `START` and `DRAFT` are deliberately absent -- "
                    f"see sim/mfl.py for why they are a different population rather than a "
                    f"later window."
                )
            month, day = PERIOD_STARTS[period]
            return date(season, month, day)
        return date(season, 12, 31)  # unused for FFC; load_board reads meta.end_date

    def board_source_prefix(self) -> str:
        """`board_source` without the season, for a `startswith` check."""
        if self.source == MFL:
            from .mfl import MflParams

            return f"mfl_adp_{MflParams(**self.params).slug()}_"
        return "ffc_adp_standard_8_"

    def board_source(self, season: int) -> str:
        """The provenance string a projected line carries for this market's board.

        `sim/projection.py` and `sim/ffa.py` both stamp the board they were built from into a
        line's provenance, and `projection.assert_pre_draft` then checks it. Both used to write
        the FFC filename unconditionally, so on an MFL run the check compared a string the code
        had just written against a prefix it also owned -- true by construction, and blind to
        the file actually read.
        """
        if self.source == MFL:
            from .mfl import MflParams

            return f"mfl_adp_{MflParams(**self.params).slug()}_{season}"
        return f"ffc_adp_standard_8_{season}"


# The markets this repo knows how to build. Adding one is a dict entry plus, for a new source,
# a `pins`/`asof` branch and a loader.
#
# `ffc_12_std` is the market every result before B8 was measured in. Its name says 12 because
# that is what the files contain, whatever their filenames say -- the mismatch between
# `ffc_adp_standard_8_*.json` and `meta.teams == 12` is the confound this module exists to
# quantify, and naming the market honestly is the first step.
REGISTRY: dict[str, Market] = {
    "ffc_12_std": Market(
        name="ffc_12_std",
        league="espn_davis_drive",
        source=FFC,
        provenance="ffc_adp",
    ),
    "mfl_8_std": Market(
        name="mfl_8_std",
        league="espn_davis_drive",
        source=MFL,
        params={"fcount": 8, "is_ppr": 0, "is_mock": 0, "is_keeper": "N", "period": "AUG15"},
        provenance="mfl_adp",
    ),
    # The SAME source at twelve teams, which is what makes the team-count effect measurable
    # holding the population fixed. Without it, `mfl_8_std` against `ffc_12_std` confounds team
    # count with which website's drafters these are.
    "mfl_12_std": Market(
        name="mfl_12_std",
        league="espn_davis_drive",
        source=MFL,
        params={"fcount": 12, "is_ppr": 0, "is_mock": 0, "is_keeper": "N", "period": "AUG15"},
        provenance="mfl_adp",
    ),
}

DEFAULT = "ffc_12_std"
_active: Market = REGISTRY[DEFAULT]


def active() -> Market:
    return _active


def get(name: str) -> Market:
    if name not in REGISTRY:
        raise ValueError(f"unknown market {name!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[name]


def set_active(market: Market | str) -> Market:
    """Set the market for the rest of the process. The runner calls this once, from config."""
    global _active
    _active = get(market) if isinstance(market, str) else market
    return _active


@contextlib.contextmanager
def use(market: Market | str) -> Iterator[Market]:
    """Scope a market to a block. Restores the previous one even if the block raises."""
    global _active
    previous = _active
    try:
        yield set_active(market)
    finally:
        _active = previous
