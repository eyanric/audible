"""What to fetch, in what order, and what a restart may skip.

RESUME IS THE MANIFEST PLUS THE DISK, and it needs both. The manifest alone would skip a job
whose file was deleted; the disk alone would keep a file that failed verification and was
never recorded. A job is done only when the manifest names it AND a file of the recorded size
sits beside it.

ORDER IS COST. Weighted jobs need no Settings round trip -- a year change already resets the
aggregation to weighted server-side -- so they run in roughly a third of the time. The stages
below put the cheapest useful data first, so a run killed at any point has left the most
valuable corpus it could for the wall clock it spent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .manifest import ManifestEntry
from .naming import AVG_TYPES, filename

# The week dropdown offers weekly periods only from 2015. Before that a season has week 0
# and nothing else, so a 2014 weekly job is not merely empty -- it is unrequestable.
WEEKLY_FROM = 2015

# 2026 has not been played. Its week dropdown offers 0 and 1 only.
PARTIAL_YEARS: Mapping[int, tuple[int, ...]] = {2026: (0, 1)}

REGULAR_WEEKS: tuple[int, ...] = tuple(range(1, 18))
SEASON_YEARS: tuple[int, ...] = tuple(range(2018, 2027))
WEEKLY_YEARS: tuple[int, ...] = tuple(range(2015, 2026))


@dataclass(frozen=True, order=True)
class Job:
    kind: str
    year: int
    week: int
    avg: str

    @property
    def filename(self) -> str:
        return filename(self.kind, self.year, self.week, self.avg)

    @property
    def needs_settings_trip(self) -> bool:
        """The COST MODEL that orders the stages, not the driver's decision.

        A weighted job is cheap when it follows a year change, which is what leaves the app
        on weighted. It is not free unconditionally -- writing 2019 over 2019 resets nothing
        -- so `ShinyDriver.prepare` decides per job from the aggregation it believes is
        effective. This property answers "is this stage cheap in aggregate", and stage
        `weekly-weighted` is 187 jobs across 11 year changes.
        """
        return self.avg != "weighted"


class IllegalJob(ValueError):
    """A job the app cannot serve. Raised at plan time, never discovered mid-run."""


def assert_legal(job: Job) -> None:
    if job.week > 0 and job.year < WEEKLY_FROM:
        raise IllegalJob(
            f"weekly data begins at {WEEKLY_FROM}; {job.year} wk{job.week} does not exist"
        )
    allowed = PARTIAL_YEARS.get(job.year)
    if allowed is not None and job.week not in allowed:
        raise IllegalJob(
            f"{job.year} offers weeks {allowed}; wk{job.week} is not on the dropdown"
        )
    # Validates kind, avg and the year/week bounds by construction, raising NamingError.
    job.filename  # noqa: B018


def build_jobs(
    *,
    kinds: Sequence[str],
    years: Sequence[int],
    weeks: Sequence[int],
    avgs: Sequence[str],
) -> list[Job]:
    """The cross product, minus what the app cannot serve, in a deterministic order.

    Weighted first within a year so a partial run leaves the cheap corpus complete.
    """
    ordered_avgs = sorted(avgs, key=lambda a: (a != "weighted", AVG_TYPES.index(a)))
    jobs: list[Job] = []
    for year in years:
        for week in weeks:
            for avg in ordered_avgs:
                for kind in kinds:
                    job = Job(kind=kind, year=year, week=week, avg=avg)
                    try:
                        assert_legal(job)
                    except IllegalJob:
                        continue
                    jobs.append(job)
    return jobs


def season_jobs(kinds: Sequence[str], avgs: Sequence[str] = AVG_TYPES) -> list[Job]:
    return build_jobs(kinds=kinds, years=SEASON_YEARS, weeks=(0,), avgs=avgs)


def weekly_jobs(kinds: Sequence[str], avgs: Sequence[str] = ("weighted",)) -> list[Job]:
    return build_jobs(kinds=kinds, years=WEEKLY_YEARS, weeks=REGULAR_WEEKS, avgs=avgs)


STAGES: Mapping[str, list[Job]] = {
    # 1. Weekly is the point of the exercise: ~17 observations per player-season rather
    #    than one. Weighted only, so no Settings trip -- the cheapest useful data there is.
    "weekly-weighted": weekly_jobs(kinds=("raw",), avgs=("weighted",)),
    # 2/3. The season corpus across all three aggregations, raw before proj because raw
    #      self-verifies and proj does not.
    "season-raw": season_jobs(kinds=("raw",), avgs=AVG_TYPES),
    "season-proj": season_jobs(kinds=("proj",), avgs=AVG_TYPES),
    # 4. Optional. ~374 files at roughly 36s each is about four hours; only worth running
    #    once the three above are clean.
    "weekly-alt": weekly_jobs(kinds=("raw",), avgs=("average", "robust")),
}

STAGE_ORDER: tuple[str, ...] = ("weekly-weighted", "season-raw", "season-proj", "weekly-alt")


def plan(
    jobs: Iterable[Job],
    done: Mapping[str, ManifestEntry],
    on_disk: Mapping[str, int],
) -> list[Job]:
    """The jobs still to run: those the manifest and the disk do not BOTH vouch for.

    `on_disk` is a filename -> size mapping rather than a directory, so this stays pure and
    a test can drive it without a filesystem.
    """
    queued: list[Job] = []
    seen: set[str] = set()
    for job in jobs:
        name = job.filename
        if name in seen:
            continue
        seen.add(name)
        entry = done.get(name)
        if entry is not None and on_disk.get(name) == entry.bytes:
            continue
        queued.append(job)
    return queued
