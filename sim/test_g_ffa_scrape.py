"""Gate: the FFA scraper's checks, exercised rather than asserted about.

WHAT BROKE LAST TIME, and what each gate here says about it.

A prior attempt drove the FFAnalytics app by hand from a chat session. Changing the year
resets the aggregation to `weighted` server-side, so 36 files were downloaded under three
aggregation names holding one aggregation's data. Browser downloads then made it
unrecoverable: Chrome appends `(1)`, `(2)` on re-runs, so the FIRST download kept the clean
name. `ffa_raw_2019_wk0_average.csv` and `..._robust.csv` both held `weighted` rows.

Nothing detected it. That is the gap these gates close, and the reason they are written
against the CHECKS rather than against the browser: the browser is where the data comes from,
but the check is where the defect was.

EVERY GATE HERE IS OFFLINE. Payloads are synthesised in this file. `test_the_synthetic_raw_
fixture_matches_a_real_export` reconciles the fixture against a real file when one is on disk,
so the fixtures cannot drift away from what the app actually serves without saying so -- and
skips when it is not, because the corpus is gitignored and CI has none of it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from .tools.ffa_scrape import driver as driver_mod
from .tools.ffa_scrape import jobs as jobs_mod
from .tools.ffa_scrape import manifest as manifest_mod
from .tools.ffa_scrape import runner, verify
from .tools.ffa_scrape.jobs import Job, plan
from .tools.ffa_scrape.manifest import ManifestEntry, append_entry, load_manifest, sha256_of
from .tools.ffa_scrape.naming import NamingError, filename, parse_filename
from .tools.ffa_scrape.verify import NINE_POSITIONS, inspect_csv, verify_payload

# The real 63-column raw header, taken verbatim from `sim/data/ffa/raw_stats_2019_wk0.csv`.
# `avg_type` is the fifth column, which is the whole reason a raw file can self-verify.
RAW_HEADER: tuple[str, ...] = (
    "player", "team", "position", "id", "avg_type",
    "pass_yds", "pass_yds_sd", "pass_tds", "pass_tds_sd", "pass_int", "pass_int_sd",
    "rush_yds", "rush_yds_sd", "rush_tds", "rush_tds_sd", "fumbles_lost", "fumbles_lost_sd",
    "two_pts", "two_pts_sd", "return_tds", "return_tds_sd",
    "rec_yds", "rec_yds_sd", "rec_tds", "rec_tds_sd",
    "fg_0019", "fg_0019_sd", "fg_2029", "fg_2029_sd", "fg_3039", "fg_3039_sd",
    "fg_4049", "fg_4049_sd", "fg_50", "fg_50_sd", "xp", "xp_sd",
    "dst_int", "dst_int_sd", "dst_sacks", "dst_sacks_sd", "dst_safety", "dst_safety_sd",
    "dst_td", "dst_td_sd", "dst_blk", "dst_blk_sd",
    "idp_solo", "idp_solo_sd", "idp_sack", "idp_sack_sd", "idp_int", "idp_int_sd",
    "idp_pd", "idp_pd_sd", "idp_td", "idp_td_sd",
    "draft_year", "birthdate", "injury_status", "injury_details", "season_year", "week",
)

# The real 22-column proj header. It carries NO aggregation column, which is exactly why a
# proj file is unverifiable and why the corpus prefers raw.
PROJ_HEADER: tuple[str, ...] = (
    "player", "position", "team", "bye_week", "points", "sd_pts", "dropoff", "floor",
    "ceiling", "points_vor", "floor_vor", "ceiling_vor", "rank", "floor_rank",
    "ceiling_rank", "position_rank", "tier", "age", "adp", "aav", "uncertainty",
    "experience",
)

POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DST", "DL", "LB", "DB")


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def raw_csv(
    *,
    avg_type: str = "weighted",
    per_position: int = 60,
    positions: tuple[str, ...] = POSITIONS,
    header: tuple[str, ...] = RAW_HEADER,
) -> str:
    """A synthetic raw export. Shaped like the real thing where the checks look."""
    lines = [",".join(_quote(column) for column in header)]
    pos_index = header.index("position")
    avg_index = header.index("avg_type") if "avg_type" in header else None
    for position in positions:
        for n in range(per_position):
            row = ["0"] * len(header)
            row[0] = _quote(f"{position} Player {n}")
            row[1] = _quote("KC")
            row[pos_index] = _quote(position)
            row[3] = _quote(str(10000 + n))
            if avg_index is not None:
                row[avg_index] = _quote(avg_type)
            lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def proj_csv(*, per_position: int = 40, positions: tuple[str, ...] = POSITIONS) -> str:
    lines = [",".join(_quote(column) for column in PROJ_HEADER)]
    for position in positions:
        for n in range(per_position):
            row = ["0"] * len(PROJ_HEADER)
            row[0] = _quote(f"{position} Player {n}")
            row[1] = _quote(position)
            row[2] = _quote("KC")
            lines.append(",".join(row))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# G2 -- the avg_type verifier. The check that was missing when 36 files shipped mislabelled.
# ---------------------------------------------------------------------------------------


def test_a_weighted_payload_asked_for_as_average_is_rejected() -> None:
    """THE gate. This is the defect, reproduced exactly: a year change reset the
    aggregation server-side and the download came back weighted under an average name."""
    payload = raw_csv(avg_type="weighted")
    reasons = verify_payload(payload, kind="raw", week=0, avg="average")
    assert reasons, "a weighted payload was accepted for an average job"
    assert any(r.startswith("avg-type-mismatch") for r in reasons), reasons
    assert "weighted" in reasons[0] or any("weighted" in r for r in reasons)


def test_the_same_payload_asked_for_as_weighted_is_accepted() -> None:
    """The CONTROL. Without it a verifier that rejects everything would pass the gate above."""
    payload = raw_csv(avg_type="weighted")
    assert verify_payload(payload, kind="raw", week=0, avg="weighted") == []


@pytest.mark.parametrize("wanted", ["weighted", "average", "robust"])
def test_each_aggregation_accepts_only_its_own(wanted: str) -> None:
    """Not just weighted-for-average. Every off-diagonal pair is rejected."""
    for held in ("weighted", "average", "robust"):
        reasons = verify_payload(raw_csv(avg_type=held), kind="raw", week=0, avg=wanted)
        if held == wanted:
            assert reasons == [], f"{held} rejected for its own job: {reasons}"
        else:
            assert any(r.startswith("avg-type-mismatch") for r in reasons), (
                f"{held} accepted for a {wanted} job"
            )


def test_a_payload_holding_two_aggregations_is_rejected() -> None:
    """A mid-file switch is not a partial success. Neither half is what was asked for."""
    mixed = raw_csv(avg_type="weighted") + raw_csv(avg_type="robust").split("\n", 1)[1]
    reasons = verify_payload(mixed, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("avg-type-mismatch") for r in reasons), reasons


def test_a_raw_payload_that_lost_its_aggregation_column_is_rejected() -> None:
    header = tuple(c for c in RAW_HEADER if c != "avg_type")
    payload = raw_csv(header=header)
    reasons = verify_payload(payload, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("avg-type-column-absent") for r in reasons), reasons


def test_a_moved_aggregation_column_is_rejected_even_though_the_values_are_right() -> None:
    """Read-by-name would still find it. Stopping is the correct response to a schema change:
    the position claim this tool rests on is that avg_type is the FIFTH column."""
    header = ("avg_type",) + tuple(c for c in RAW_HEADER if c != "avg_type")
    payload = raw_csv(avg_type="average", header=header)
    reasons = verify_payload(payload, kind="raw", week=0, avg="average")
    assert any(r.startswith("avg-type-column-moved") for r in reasons), reasons
    assert not any(r.startswith("avg-type-mismatch") for r in reasons), (
        "the values were correct; only the column moved"
    )


def test_a_proj_payload_is_accepted_without_an_aggregation_claim() -> None:
    """proj files carry no avg_type. They are unverifiable, not invalid."""
    assert verify_payload(proj_csv(), kind="proj", week=0, avg="robust") == []
    assert inspect_csv(proj_csv()).sole_avg_type is None


def test_a_proj_payload_that_gained_an_aggregation_column_is_rejected() -> None:
    """If FFA ever adds one, the unverifiable-by-construction assumption is stale and the
    tool must be told rather than quietly keep treating proj as unverifiable."""
    reasons = verify_payload(raw_csv(), kind="proj", week=0, avg="weighted")
    assert any(r.startswith("avg-type-column-unexpected") for r in reasons), reasons


# ---------------------------------------------------------------------------------------
# Position completeness. The Position dropdown filters the CHART only -- a download always
# carries all nine, so a file missing one is a defective download, not a narrower request.
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("dropped", POSITIONS)
def test_a_payload_missing_any_one_position_is_rejected(dropped: str) -> None:
    kept = tuple(p for p in POSITIONS if p != dropped)
    payload = raw_csv(positions=kept)
    reasons = verify_payload(payload, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("positions-missing") for r in reasons), reasons
    assert dropped in reasons[0] or any(dropped in r for r in reasons)


def test_the_nine_positions_are_the_nine_measured_on_a_real_export() -> None:
    assert set(POSITIONS) == NINE_POSITIONS
    assert len(NINE_POSITIONS) == 9


def test_a_complete_payload_names_no_missing_position() -> None:
    """CONTROL for the parametrised gate above."""
    reasons = verify_payload(raw_csv(), kind="raw", week=0, avg="weighted")
    assert not any(r.startswith("positions-missing") for r in reasons), reasons


# ---------------------------------------------------------------------------------------
# Row-count sanity and truncation.
# ---------------------------------------------------------------------------------------


def test_a_payload_truncated_mid_row_is_rejected() -> None:
    """A response cut short by a dropped connection. The last row has too few fields."""
    payload = raw_csv()
    truncated = payload[: len(payload) - 40]
    reasons = verify_payload(truncated, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("ragged-rows") for r in reasons), reasons


def test_a_payload_truncated_to_a_stub_is_rejected_on_row_count() -> None:
    """A clean cut at a row boundary leaves no ragged row, so the floor is what catches it."""
    payload = raw_csv(per_position=2)
    reasons = verify_payload(payload, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("row-count") for r in reasons), reasons


def test_a_header_only_payload_is_rejected() -> None:
    header_only = raw_csv().split("\n", 1)[0] + "\n"
    reasons = verify_payload(header_only, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("row-count") for r in reasons), reasons


def test_an_empty_payload_is_rejected_rather_than_raising() -> None:
    assert verify_payload("", kind="raw", week=0, avg="weighted") == [
        "empty-payload: payload has no header row"
    ]


def test_the_weekly_floor_is_lower_than_the_season_floor() -> None:
    """A week 5 file is a fraction of a season file. One floor for both would either reject
    good weekly files or wave through truncated season ones."""
    assert verify.min_rows_for("raw", 5) < verify.min_rows_for("raw", 0)
    assert verify.min_rows_for("proj", 5) < verify.min_rows_for("proj", 0)


def test_a_small_but_complete_weekly_payload_passes_at_the_weekly_floor() -> None:
    """CONTROL: the lower floor is not decorative -- this payload fails the season floor."""
    payload = raw_csv(per_position=20)
    assert verify_payload(payload, kind="raw", week=5, avg="weighted") == []
    assert any(
        r.startswith("row-count")
        for r in verify_payload(payload, kind="raw", week=0, avg="weighted")
    )


# ---------------------------------------------------------------------------------------
# Filenames. Chrome's (1)/(2) suffixing is what made the prior attempt unrecoverable.
# ---------------------------------------------------------------------------------------


def test_the_filename_is_exactly_the_documented_shape() -> None:
    assert filename("raw", 2019, 0, "weighted") == "ffa_raw_2019_wk0_weighted.csv"
    assert filename("proj", 2026, 17, "robust") == "ffa_proj_2026_wk17_robust.csv"
    assert filename("raw", 2015, 1, "average") == "ffa_raw_2015_wk1_average.csv"


def test_the_filename_is_deterministic_and_sensitive_to_every_argument() -> None:
    """Stability alone is satisfied by a function that returns a constant -- which would
    overwrite the whole corpus into one file -- so sensitivity is asserted beside it."""
    calls = [filename("raw", 2022, 9, "robust") for _ in range(50)]
    assert len(set(calls)) == 1

    base = filename("raw", 2022, 9, "robust")
    assert filename("proj", 2022, 9, "robust") != base
    assert filename("raw", 2023, 9, "robust") != base
    assert filename("raw", 2022, 10, "robust") != base
    assert filename("raw", 2022, 9, "average") != base


def test_every_job_in_every_stage_has_a_unique_filename() -> None:
    """A collision would silently overwrite. 615 jobs, 615 names."""
    all_jobs = [job for stage in jobs_mod.STAGE_ORDER for job in jobs_mod.STAGES[stage]]
    names = [job.filename for job in all_jobs]
    assert len(names) == len(set(names)) == len(all_jobs)


def test_a_chrome_suffixed_name_is_not_a_corpus_name() -> None:
    """The exact shape that put weighted data under a clean average name."""
    with pytest.raises(NamingError):
        parse_filename("ffa_raw_2019_wk0_average (1).csv")


@pytest.mark.parametrize(
    "bad",
    [
        "ffa_raw_2019_wk00_average.csv",
        "ffa_raw_2019_wk0_mean.csv",
        "ffa_stats_2019_wk0_average.csv",
        "ffa_raw_19_wk0_average.csv",
        "raw_2019_wk0_average.csv",
        "ffa_raw_2019_wk0_average.CSV",
        "ffa_raw_2019_wk0_average.csv.part",
    ],
)
def test_names_the_tool_never_emits_do_not_parse(bad: str) -> None:
    with pytest.raises(NamingError):
        parse_filename(bad)


def test_names_round_trip_through_parse_for_every_job() -> None:
    for stage in jobs_mod.STAGE_ORDER:
        for job in jobs_mod.STAGES[stage]:
            kind, year, week, avg = parse_filename(job.filename)
            assert (kind, year, week, avg) == (job.kind, job.year, job.week, job.avg)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "stats", "year": 2019, "week": 0, "avg": "weighted"},
        {"kind": "raw", "year": 2019, "week": 0, "avg": "mean"},
        {"kind": "raw", "year": 2007, "week": 0, "avg": "weighted"},
        {"kind": "raw", "year": 2027, "week": 0, "avg": "weighted"},
        {"kind": "raw", "year": 2019, "week": -1, "avg": "weighted"},
        {"kind": "raw", "year": 2019, "week": 22, "avg": "weighted"},
    ],
)
def test_an_unnameable_job_raises_rather_than_reaching_disk(kwargs: dict) -> None:
    with pytest.raises(NamingError):
        filename(**kwargs)


# ---------------------------------------------------------------------------------------
# Resume. The shinyapps session WILL reload mid-run; the manifest is what survives it.
# ---------------------------------------------------------------------------------------


def _entry(job: Job, size: int = 1234) -> ManifestEntry:
    return ManifestEntry(
        file=job.filename, kind=job.kind, year=job.year, week=job.week, avg=job.avg,
        sha256="0" * 64, bytes=size, rows=999, measured_avg_type=job.avg,
        positions={p: 1 for p in POSITIONS}, fetched_at="2026-09-10T00:00:00Z",
    )


def test_only_the_jobs_the_manifest_does_not_vouch_for_are_queued() -> None:
    all_jobs = jobs_mod.STAGES["season-raw"]
    assert len(all_jobs) == 27
    done_jobs = all_jobs[:10]
    done = {job.filename: _entry(job) for job in done_jobs}
    on_disk = {job.filename: 1234 for job in done_jobs}
    queued = plan(all_jobs, done, on_disk)
    assert len(queued) == 27 - 10
    assert {job.filename for job in queued}.isdisjoint(done)


def test_a_manifest_entry_without_its_file_is_re_queued() -> None:
    """The manifest alone is not enough. A recorded file that is gone is a gap, not a skip."""
    all_jobs = jobs_mod.STAGES["season-raw"]
    done = {job.filename: _entry(job) for job in all_jobs}
    queued = plan(all_jobs, done, on_disk={})
    assert len(queued) == len(all_jobs)


def test_a_file_whose_size_disagrees_with_the_manifest_is_re_queued() -> None:
    """A half-written file left by a kill during the write, not during the append."""
    all_jobs = jobs_mod.STAGES["season-raw"]
    done = {job.filename: _entry(job) for job in all_jobs}
    on_disk = {job.filename: 1234 for job in all_jobs}
    on_disk[all_jobs[3].filename] = 900
    queued = plan(all_jobs, done, on_disk)
    assert [job.filename for job in queued] == [all_jobs[3].filename]


def test_deleting_one_manifest_entry_re_fetches_that_file_alone() -> None:
    """FAILURE INJECTION 2, as a gate."""
    all_jobs = jobs_mod.STAGES["season-raw"]
    done = {job.filename: _entry(job) for job in all_jobs}
    on_disk = {job.filename: 1234 for job in all_jobs}
    assert plan(all_jobs, done, on_disk) == []
    victim = all_jobs[7]
    del done[victim.filename]
    assert plan(all_jobs, done, on_disk) == [victim]


def test_a_completed_corpus_queues_nothing() -> None:
    """Idempotence. Re-running after a full completion must fetch nothing at all."""
    all_jobs = [job for stage in jobs_mod.STAGE_ORDER for job in jobs_mod.STAGES[stage]]
    done = {job.filename: _entry(job) for job in all_jobs}
    on_disk = {job.filename: 1234 for job in all_jobs}
    assert plan(all_jobs, done, on_disk) == []


def test_a_kill_and_restart_mid_list_skips_nothing_and_repeats_nothing(
    tmp_path: Path,
) -> None:
    """G3 in miniature, with a real manifest file and a real kill point.

    Run the first 40 of 187 jobs, stop dead, reload the manifest from disk, and confirm the
    union of the two passes is the job list exactly once.
    """
    path = tmp_path / manifest_mod.MANIFEST_NAME
    all_jobs = jobs_mod.STAGES["weekly-weighted"]
    assert len(all_jobs) == 187

    on_disk: dict[str, int] = {}
    first_pass: list[Job] = []
    for job in plan(all_jobs, load_manifest(path), on_disk):
        if len(first_pass) == 40:
            break  # the kill
        append_entry(path, _entry(job))
        on_disk[job.filename] = 1234
        first_pass.append(job)

    second_pass = plan(all_jobs, load_manifest(path), on_disk)
    assert len(first_pass) == 40
    assert len(second_pass) == 147
    assert first_pass + second_pass == all_jobs


def test_a_torn_final_manifest_line_costs_one_file_and_not_the_run(tmp_path: Path) -> None:
    """A kill DURING the append. The half-written line is dropped; that job is re-fetched."""
    path = tmp_path / manifest_mod.MANIFEST_NAME
    all_jobs = jobs_mod.STAGES["season-raw"][:5]
    for job in all_jobs:
        append_entry(path, _entry(job))
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) - 25], encoding="utf-8")

    entries = load_manifest(path)
    assert len(entries) == 4
    on_disk = {job.filename: 1234 for job in all_jobs}
    assert plan(all_jobs, entries, on_disk) == [all_jobs[4]]


def test_a_corrupt_line_that_is_not_the_last_one_raises(tmp_path: Path) -> None:
    """Only a TORN TAIL is survivable. Damage in the middle is not a crash artefact and
    must not be swallowed."""
    path = tmp_path / manifest_mod.MANIFEST_NAME
    for job in jobs_mod.STAGES["season-raw"][:3]:
        append_entry(path, _entry(job))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0][:20]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_manifest(path)


def test_a_re_fetched_file_replaces_its_earlier_manifest_entry(tmp_path: Path) -> None:
    path = tmp_path / manifest_mod.MANIFEST_NAME
    job = jobs_mod.STAGES["season-raw"][0]
    append_entry(path, _entry(job, size=100))
    append_entry(path, _entry(job, size=200))
    entries = load_manifest(path)
    assert len(entries) == 1
    assert entries[job.filename].bytes == 200


def test_a_manifest_entry_carries_every_field_the_report_promises(tmp_path: Path) -> None:
    """G6. filename, sha256, bytes, rows, avg_type -- per file."""
    path = tmp_path / manifest_mod.MANIFEST_NAME
    payload = raw_csv(avg_type="average")
    report = inspect_csv(payload)
    entry = ManifestEntry(
        file="ffa_raw_2019_wk0_average.csv", kind="raw", year=2019, week=0, avg="average",
        sha256=sha256_of(payload), bytes=len(payload.encode("utf-8")), rows=report.rows,
        measured_avg_type=report.sole_avg_type, positions=dict(report.positions),
        fetched_at="2026-09-10T12:00:00Z",
    )
    append_entry(path, entry)
    loaded = load_manifest(path)["ffa_raw_2019_wk0_average.csv"]
    assert loaded.sha256 == sha256_of(payload) and len(loaded.sha256) == 64
    assert loaded.bytes == len(payload.encode("utf-8"))
    assert loaded.rows == 9 * 60
    assert loaded.measured_avg_type == "average"
    assert set(loaded.positions) == NINE_POSITIONS
    assert loaded.fetched_at


def test_a_proj_manifest_entry_records_no_aggregation_claim() -> None:
    """It must not echo the requested aggregation back as though it had been checked."""
    report = inspect_csv(proj_csv())
    assert report.sole_avg_type is None


# ---------------------------------------------------------------------------------------
# The job list itself.
# ---------------------------------------------------------------------------------------


def test_the_stages_are_the_sizes_the_plan_promises() -> None:
    assert len(jobs_mod.STAGES["weekly-weighted"]) == 187  # 11 seasons x 17 weeks
    assert len(jobs_mod.STAGES["season-raw"]) == 27  # 9 seasons x 3 aggregations
    assert len(jobs_mod.STAGES["season-proj"]) == 27
    assert len(jobs_mod.STAGES["weekly-alt"]) == 374  # 11 x 17 x 2


def test_weekly_before_2015_is_never_queued() -> None:
    """The week dropdown offers no weekly period before 2015."""
    with pytest.raises(jobs_mod.IllegalJob):
        jobs_mod.assert_legal(Job(kind="raw", year=2014, week=1, avg="weighted"))
    built = jobs_mod.build_jobs(
        kinds=("raw",), years=(2013, 2014, 2015), weeks=(1,), avgs=("weighted",)
    )
    assert [job.year for job in built] == [2015]


def test_2026_offers_only_week_0_and_week_1() -> None:
    with pytest.raises(jobs_mod.IllegalJob):
        jobs_mod.assert_legal(Job(kind="raw", year=2026, week=2, avg="weighted"))
    jobs_mod.assert_legal(Job(kind="raw", year=2026, week=1, avg="weighted"))
    jobs_mod.assert_legal(Job(kind="raw", year=2026, week=0, avg="weighted"))
    assert not [job for job in jobs_mod.STAGES["weekly-weighted"] if job.year == 2026]


def test_only_weighted_skips_the_settings_round_trip() -> None:
    """The cost model the stage order rests on."""
    assert not Job(kind="raw", year=2019, week=0, avg="weighted").needs_settings_trip
    assert Job(kind="raw", year=2019, week=0, avg="average").needs_settings_trip
    assert Job(kind="raw", year=2019, week=0, avg="robust").needs_settings_trip


def test_weighted_is_ordered_first_within_a_year() -> None:
    """So a run killed part way leaves the cheap corpus complete rather than interleaved."""
    built = jobs_mod.build_jobs(
        kinds=("raw",), years=(2019,), weeks=(0,), avgs=("robust", "average", "weighted")
    )
    assert [job.avg for job in built] == ["weighted", "average", "robust"]


# ---------------------------------------------------------------------------------------
# Fixture reconciliation. Skips when the gitignored corpus is absent, which is CI.
# ---------------------------------------------------------------------------------------

_REAL = Path(__file__).resolve().parent / "data" / "ffa" / "raw_stats_2019_wk0.csv"


@pytest.mark.skipif(not _REAL.exists(), reason="gitignored corpus not on this machine")
def test_the_synthetic_raw_fixture_matches_a_real_export() -> None:
    """The fixtures above are only worth anything if they are shaped like the real thing."""
    real = inspect_csv(_REAL.read_text(encoding="utf-8"))
    assert real.columns == RAW_HEADER
    assert real.columns[4] == "avg_type"
    assert set(real.positions) == NINE_POSITIONS
    assert real.ragged == 0
    assert real.sole_avg_type == "weighted"
    assert verify_payload(
        _REAL.read_text(encoding="utf-8"), kind="raw", week=0, avg="weighted"
    ) == []


# ---------------------------------------------------------------------------------------
# G9 -- the corpus is subscription data and this repository is public.
# ---------------------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[1]


def _tracked(pattern: str) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", pattern],
        cwd=_REPO, capture_output=True, text=True, check=True,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def test_no_csv_is_tracked_anywhere_in_the_repository() -> None:
    """Not `sim/data/ffa_corpus/` specifically -- ANY csv. A file dropped in the wrong
    directory is exactly how paid data reaches a public remote, and the narrower gate would
    not see it."""
    assert _tracked("*.csv") == []


def test_the_corpus_directory_is_ignored_by_git() -> None:
    """The gate above is the outcome; this is the mechanism, so a removed .gitignore line
    fails here with a name rather than only when someone happens to add a file."""
    proc = subprocess.run(
        ["git", "check-ignore", "-v", "sim/data/ffa_corpus/ffa_raw_2019_wk0_weighted.csv"],
        cwd=_REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, "a corpus CSV is NOT ignored by git"
    assert ".gitignore" in proc.stdout


def test_the_manifest_and_readme_are_the_only_things_meant_to_be_committed() -> None:
    tracked = _tracked("sim/data/ffa_corpus/*")
    assert set(tracked) <= {
        "sim/data/ffa_corpus/README.md",
        "sim/data/ffa_corpus/manifest.jsonl",
    }, tracked


# ---------------------------------------------------------------------------------------
# Gaps the mutation sweep found. Each of these was added because a mutation SURVIVED --
# `sole-avg-type-guesses-when-mixed`, `the-job-list-is-not-deduplicated` and
# `the-sha256-is-of-the-name-not-the-bytes` all passed a green suite before they existed.
# ---------------------------------------------------------------------------------------


def test_a_mixed_payload_has_no_sole_aggregation_to_record() -> None:
    """`sole_avg_type` is what reaches the manifest. Reporting one of two aggregations would
    write a manifest line claiming a purity the file does not have."""
    mixed = raw_csv(avg_type="weighted") + raw_csv(avg_type="robust").split("\n", 1)[1]
    report = inspect_csv(mixed)
    assert report.avg_types == frozenset({"weighted", "robust"})
    assert report.sole_avg_type is None


def test_a_job_list_with_duplicates_queues_each_file_once() -> None:
    """A stage list built from overlapping ranges must not fetch the same file twice --
    the second fetch would spend a minute to overwrite identical bytes on a server we are
    deliberately being gentle with."""
    job = Job(kind="raw", year=2019, week=0, avg="weighted")
    assert plan([job, job, job], done={}, on_disk={}) == [job]
    other = Job(kind="raw", year=2020, week=0, avg="weighted")
    assert plan([job, other, job, other], done={}, on_disk={}) == [job, other]


def test_the_sha256_is_of_the_payload_bytes() -> None:
    """Pinned against a constant rather than against `sha256_of` itself. Asserting
    `sha256_of(x) == sha256_of(x)` is true of a function that hashes nothing at all, and a
    manifest full of one repeated digest would vouch for every file equally."""
    assert sha256_of("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert sha256_of("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert sha256_of(raw_csv()) != sha256_of(raw_csv(avg_type="robust"))


# ---------------------------------------------------------------------------------------
# The runner. Everything above tests a check in isolation; these test that the RUNNER
# actually obeys them -- that a rejected payload does not reach disk, that the manifest is
# appended only after a success, and that a lost session is recovered from rather than
# recorded as a failure.
# ---------------------------------------------------------------------------------------


class FakeDriver:
    """A scripted stand-in for `ShinyDriver`. Same three methods the runner uses.

    `script` maps a filename to what happens on each successive attempt at it: a string is
    served as the payload, an exception class is raised.
    """

    def __init__(self, script: dict[str, list[object]]) -> None:
        self.script = {name: list(steps) for name, steps in script.items()}
        self.settles = driver_mod.Settles()
        self.prepared: list[tuple[str, int, int, str]] = []
        self.establishes = 0
        self._pending: object | None = None

    def prepare(self, kind: str, year: int, week: int, avg: str) -> None:
        self.prepared.append((kind, year, week, avg))
        name = filename(kind, year, week, avg)
        steps = self.script.get(name)
        if not steps:
            raise AssertionError(f"FakeDriver has no script left for {name}")
        step = steps.pop(0)
        if isinstance(step, type) and issubclass(step, Exception):
            raise step("scripted")
        self._pending = step

    def fetch_payload(self) -> driver_mod.FetchResult:
        return driver_mod.FetchResult(
            ok=True, status=200, content_type="text/csv", text=str(self._pending)
        )

    def establish(self) -> None:
        self.establishes += 1


def _run(
    script: dict[str, list[object]], jobs: list[Job], tmp_path: Path
) -> tuple[FakeDriver, runner.RunResult]:
    fake = FakeDriver(script)
    result = runner.run_jobs(
        fake,  # type: ignore[arg-type]
        jobs,
        data_dir=tmp_path,
        manifest_path=tmp_path / manifest_mod.MANIFEST_NAME,
        now=lambda: "2026-09-10T00:00:00+00:00",
        log=lambda _msg: None,
    )
    return fake, result


def test_a_mislabelled_payload_is_never_written_and_never_recorded(tmp_path: Path) -> None:
    """FAILURE INJECTION 1, through the runner rather than the verifier. The exact defect:
    the app serves weighted data for an average job, twice, and the corpus stays clean."""
    job = Job(kind="raw", year=2019, week=0, avg="average")
    weighted = raw_csv(avg_type="weighted")
    _, result = _run({job.filename: [weighted, weighted]}, [job], tmp_path)

    assert result.completed == []
    assert [j.filename for j, _ in result.failed] == [job.filename]
    assert not (tmp_path / job.filename).exists(), "a mislabelled file reached disk"
    assert load_manifest(tmp_path / manifest_mod.MANIFEST_NAME) == {}
    reasons = result.failed[0][1]
    assert any(r.startswith("avg-type-mismatch") for r in reasons), reasons


def test_the_retry_is_what_saves_a_job_that_lost_a_race(tmp_path: Path) -> None:
    """First attempt comes back weighted; the longer second attempt comes back right."""
    job = Job(kind="raw", year=2019, week=0, avg="robust")
    _, result = _run(
        {job.filename: [raw_csv(avg_type="weighted"), raw_csv(avg_type="robust")]},
        [job],
        tmp_path,
    )
    assert result.completed == [job.filename]
    assert result.failed == []
    entry = load_manifest(tmp_path / manifest_mod.MANIFEST_NAME)[job.filename]
    assert entry.measured_avg_type == "robust"
    assert (tmp_path / job.filename).exists()


def test_a_lost_session_is_re_established_and_the_job_still_lands(tmp_path: Path) -> None:
    """G4 at the unit level. A reload resets the app; the runner rebuilds and carries on."""
    job = Job(kind="raw", year=2020, week=0, avg="weighted")
    fake, result = _run(
        {job.filename: [driver_mod.SessionLost, raw_csv(avg_type="weighted")]},
        [job],
        tmp_path,
    )
    assert fake.establishes == 1
    assert result.recoveries == 1
    assert result.completed == [job.filename]
    assert result.failed == []


def test_a_run_that_keeps_losing_its_session_stops_rather_than_hammering(
    tmp_path: Path,
) -> None:
    """Politeness, enforced. This is a personal subscription on a server we do not own."""
    jobs = jobs_mod.STAGES["season-raw"][:6]
    script = {job.filename: [driver_mod.SessionLost] * 4 for job in jobs}
    with pytest.raises(driver_mod.SessionLost):
        _run(script, jobs, tmp_path)


def test_every_job_re_sets_the_aggregation_after_the_year(tmp_path: Path) -> None:
    """Behaviour 1 has no fast path. The prepare call carries the aggregation EVERY time,
    because "it is already set" is precisely the assumption that mislabelled 36 files."""
    jobs = [
        Job(kind="raw", year=2019, week=0, avg="average"),
        Job(kind="raw", year=2019, week=0, avg="robust"),
        Job(kind="raw", year=2020, week=0, avg="average"),
    ]
    script = {job.filename: [raw_csv(avg_type=job.avg)] for job in jobs}
    fake, result = _run(script, jobs, tmp_path)
    assert len(result.completed) == 3
    assert fake.prepared == [(j.kind, j.year, j.week, j.avg) for j in jobs]


def test_a_run_records_each_success_before_it_starts_the_next_job(tmp_path: Path) -> None:
    """A kill after job N leaves N manifest lines, not zero. This is what resume rests on."""
    jobs = jobs_mod.STAGES["season-raw"][:4]
    script = {job.filename: [raw_csv(avg_type=job.avg)] for job in jobs}
    seen: list[int] = []
    manifest_path = tmp_path / manifest_mod.MANIFEST_NAME

    runner.run_jobs(
        FakeDriver(script),  # type: ignore[arg-type]
        jobs,
        data_dir=tmp_path,
        manifest_path=manifest_path,
        now=lambda: "2026-09-10T00:00:00+00:00",
        log=lambda _msg: None,
        on_progress=lambda _i, _t, _j: seen.append(len(load_manifest(manifest_path))),
    )
    assert seen == [0, 1, 2, 3], seen


def test_an_html_login_page_is_rejected_rather_than_parsed(tmp_path: Path) -> None:
    """A logged-out session serves HTML with a 200. The CSV reader would find one column
    and no positions, but naming it for what it is makes the log readable."""
    job = Job(kind="raw", year=2019, week=0, avg="weighted")
    page = "<!DOCTYPE html>\n<html><body>Sign in</body></html>"
    _, result = _run({job.filename: [page, page]}, [job], tmp_path)
    assert result.completed == []
    assert any(r.startswith("html-payload") for r in result.failed[0][1])
    assert not (tmp_path / job.filename).exists()


def test_the_bytes_on_disk_are_the_bytes_that_were_hashed(tmp_path: Path) -> None:
    """No newline translation. On Windows a text-mode write turns every LF into CRLF and the
    file no longer hashes to what the manifest claims -- which would make every sha256 in the
    manifest a lie on exactly one platform, and that platform is the one this runs on."""
    payload = raw_csv()
    size = runner.write_payload(tmp_path, "ffa_raw_2019_wk0_weighted.csv", payload)
    written = (tmp_path / "ffa_raw_2019_wk0_weighted.csv").read_bytes()
    assert written == payload.encode("utf-8")
    assert size == len(written)
    assert b"\r\n" not in written
    assert sha256_of(written.decode("utf-8")) == sha256_of(payload)


def test_no_part_file_survives_a_completed_write(tmp_path: Path) -> None:
    runner.write_payload(tmp_path, "ffa_raw_2019_wk0_weighted.csv", raw_csv())
    assert list(tmp_path.glob("*.part")) == []
    assert (tmp_path / "ffa_raw_2019_wk0_weighted.csv").exists()


# ---------------------------------------------------------------------------------------
# The driver's ORDER. This is the mechanism of the original defect, and until now nothing
# tested it -- `verify.py` catches a mislabelled file, but catching it every time is a run
# that never finishes. The order is what makes the file right in the first place.
#
# `FakeShinyPage` models the app's three measured behaviours rather than the driver's
# expectations of them:
#   1. setting the year resets the aggregation to `weighted`
#   2. an aggregation set on the Projections page does not take; it takes on a
#      Settings -> Projections round trip
#   3. `weighted` therefore needs no round trip, because a year change leaves it there
# ---------------------------------------------------------------------------------------

INSTANT = driver_mod.Settles(
    action=0.0, after_year=0.0, after_week=0.0, after_avg=0.0,
    after_tab_proj=0.0, after_kind=0.0, idle_timeout=0.01,
)


class FakeShinyPage:
    """The app as measured, not as hoped. Serves a payload built from its EFFECTIVE state."""

    def __init__(self, *, session: str = "s1") -> None:
        self.session = session
        self.tab = "tab_proj"
        # What the widgets read.
        self.inputs = {
            driver_mod.YEAR_INPUT: "2026",
            driver_mod.WEEK_INPUT: "0",
            driver_mod.AVG_INPUT: "weighted",
            driver_mod.KIND_INPUT: "proj",
        }
        # What the SERVER will actually serve. Behaviour 2: this only catches up with the
        # widget on a Settings -> Projections round trip.
        self.effective_avg = "weighted"
        self.link_text = driver_mod.READY_TEXT
        self.calls: list[str] = []
        self.reload_before_fetch = False
        # A reload that lands mid-sequence. `after` reverts the input just written -- the
        # per-write read-back catches that. `before` lets the write land on a freshly reset
        # page, so the input just written looks RIGHT and the earlier ones have reverted;
        # only the combined read-back at the end of `prepare` sees it.
        self.reset_after_set: str | None = None
        self.reset_before_set: str | None = None
        # The five that never resolve, by their real ids.
        self.stuck_outputs: list[str] = [
            "settings_page-settings_tiering_ui",
            "optimizer_page-optimizer-optimizer_display_ui",
            "accuracy_page-acc_ui",
            "account_page-user_subscription_box-cportal",
            "controlbar-help_links",
        ]
        # Outputs genuinely recalculating right now, which SHOULD hold a wait_idle.
        self.working: list[str] = []
        self.pending = 0
        # False models a cold worker: the widgets exist and Shiny has not
        # filled them in yet.
        self.populated = True

    # -- playwright surface -------------------------------------------------------------

    def goto(self, _url: str, **_kwargs: object) -> None:
        self.calls.append("goto")
        self.reset()

    def wait_for_function(self, expr: str, **_kwargs: object) -> None:
        # The readiness wait is a real gate, not a formality: it is what separates a
        # populated app from its loading screen. The model refuses it while the year
        # dropdown is empty, so a driver that stopped waiting would read '' here exactly as
        # the live headless session did.
        if driver_mod.YEAR_INPUT in expr and not self.inputs[driver_mod.YEAR_INPUT]:
            raise TimeoutError("year dropdown never populated")

    def wait_for_selector(self, _selector: str, **_kwargs: object) -> None:
        return None

    def click(self, selector: str) -> None:
        tab = selector.split('"')[1]
        self.calls.append(f"click:{tab}")
        if self.tab == "tab_settings" and tab == "tab_proj":
            self.effective_avg = self.inputs[driver_mod.AVG_INPUT]  # behaviour 2
        self.tab = tab

    def evaluate(self, script: str, arg: object = None) -> object:
        if script is driver_mod._BUSY_JS:
            # MEASURED on the live app: five outputs on tabs this run never opens stay
            # `.recalculating` forever. The model carries them, so a driver that waits for
            # "nothing is recalculating" hangs here exactly as it hung in production.
            return {"busy": [*self.stuck_outputs, *self.working], "pending": self.pending}
        if script is driver_mod._GET_JS:
            key = str(arg)
            if key not in self.inputs:
                return {"found": False, "value": None}
            return {"found": True, "value": self.inputs[key]}
        if script is driver_mod._SET_JS:
            key, value = arg  # type: ignore[misc]
            self.calls.append(f"set:{key}={value}")
            if key == self.reset_before_set:
                self.reset_before_set = None
                self.reset()
                self.session = "s2"
            if key == driver_mod.YEAR_INPUT and value != self.inputs[key]:
                # BEHAVIOUR 1. The whole reason this tool exists.
                self.inputs[driver_mod.AVG_INPUT] = "weighted"
                self.effective_avg = "weighted"
            self.inputs[key] = value
            if key == self.reset_after_set:
                self.reset_after_set = None
                self.reset()
                self.session = "s2"
            return True
        if script is driver_mod._HREF_JS:
            # MEASURED: relative, no worker prefix. The absolute form the driver was first
            # written against does not occur.
            return {
                "found": True,
                "href": (
                    f"session/{self.session}/download/"
                    "projections_page-proj-download_projections-download?w=32ee825b"
                ),
                "text": self.link_text,
            }
        if script is driver_mod._FETCH_JS:
            if self.reload_before_fetch:
                self.reset()
                self.session = "s2"
            return {
                "ok": True,
                "status": 200,
                "type": "text/csv",
                "text": self.serve(),
            }
        raise AssertionError(f"FakeShinyPage does not model this script:\n{script[:80]}")

    # -- the app ------------------------------------------------------------------------

    def reset(self) -> None:
        """What a shinyapps.io reload leaves behind: 2026, week 0, file type proj."""
        self.calls.append("reset")
        self.inputs = {
            driver_mod.YEAR_INPUT: "2026" if self.populated else "",
            driver_mod.WEEK_INPUT: "0" if self.populated else "",
            driver_mod.AVG_INPUT: "weighted",
            driver_mod.KIND_INPUT: "proj",
        }
        self.effective_avg = "weighted"
        self.tab = "tab_proj"

    def serve(self) -> str:
        if self.inputs[driver_mod.KIND_INPUT] == "proj":
            return proj_csv()
        return raw_csv(avg_type=self.effective_avg)


def _driver_on(page: FakeShinyPage) -> driver_mod.ShinyDriver:
    return driver_mod.ShinyDriver(page, INSTANT, log=lambda _m: None)


def test_the_driver_fetches_the_aggregation_it_was_asked_for(tmp_path: Path) -> None:
    """Against an app that resets the aggregation on every year change, all three land."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    for avg in ("weighted", "average", "robust"):
        driver.prepare("raw", 2019, 0, avg)
        payload = driver.fetch_payload()
        assert verify_payload(payload.text, kind="raw", week=0, avg=avg) == [], avg


def test_setting_the_aggregation_before_the_year_would_lose_it() -> None:
    """The CONTROL for the order, and the defect reproduced against the model.

    This is what a reasonable person writes first, and it is what shipped 36 mislabelled
    files. If this ever stops failing, `FakeShinyPage` has stopped modelling the app and
    the gate above proves nothing."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()

    driver.click_tab("tab_settings")
    driver.set_input(driver_mod.AVG_INPUT, "average", 0.0)
    driver.click_tab("tab_proj")
    driver.set_input(driver_mod.YEAR_INPUT, "2019", 0.0)  # <- resets it
    driver.set_input(driver_mod.KIND_INPUT, "raw", 0.0)

    payload = driver.fetch_payload()
    reasons = verify_payload(payload.text, kind="raw", week=0, avg="average")
    assert any(r.startswith("avg-type-mismatch") for r in reasons), reasons
    assert inspect_csv(payload.text).sole_avg_type == "weighted"


def test_an_aggregation_set_without_the_round_trip_does_not_take() -> None:
    """Behaviour 2, isolated. Setting it on the Projections page changes the widget and
    not the server, which is the trap: the page reads `average` and serves `weighted`."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    driver.click_tab("tab_proj")
    driver.set_input(driver_mod.YEAR_INPUT, "2019", 0.0)
    driver.set_input(driver_mod.AVG_INPUT, "robust", 0.0)
    driver.set_input(driver_mod.KIND_INPUT, "raw", 0.0)

    assert driver.read_input(driver_mod.AVG_INPUT) == "robust"  # the widget agrees
    assert page.effective_avg == "weighted"  # the server does not
    payload = driver.fetch_payload()
    assert inspect_csv(payload.text).sole_avg_type == "weighted"


def test_a_weighted_job_makes_no_settings_trip() -> None:
    """Behaviour 3, and the reason the stage order front-loads weighted: the trip is most
    of the cost, and a year change has already left the aggregation where we want it."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    page.calls.clear()
    driver.prepare("raw", 2019, 0, "weighted")
    assert "click:tab_settings" not in page.calls, page.calls

    page.calls.clear()
    driver.prepare("raw", 2019, 0, "average")
    assert "click:tab_settings" in page.calls, page.calls


def test_the_year_is_always_set_before_the_aggregation() -> None:
    """Order, asserted directly rather than only through its consequence."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    page.calls.clear()
    driver.prepare("raw", 2022, 3, "robust")
    year_at = page.calls.index(f"set:{driver_mod.YEAR_INPUT}=2022")
    avg_at = page.calls.index(f"set:{driver_mod.AVG_INPUT}=robust")
    kind_at = page.calls.index(f"set:{driver_mod.KIND_INPUT}=raw")
    assert year_at < avg_at < kind_at, page.calls


def test_a_reload_that_reverts_the_input_just_written_is_caught_at_that_write() -> None:
    """G4 at the driver level, first shape: the per-write read-back sees the revert."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    page.reset_after_set = driver_mod.WEEK_INPUT
    with pytest.raises(driver_mod.SessionLost, match="reads '0' after being set to '5'"):
        driver.prepare("raw", 2019, 5, "weighted")


def test_a_reload_that_leaves_the_last_input_looking_right_is_caught_at_the_end() -> None:
    """The second shape, and the reason `prepare` re-reads EVERY input at the end.

    The reload lands just before the file type is written, so the file type is applied to a
    fresh page and reads back correctly -- while the year and week it was supposed to
    accompany have silently reverted to 2026 and 0. A per-write check alone would fetch a
    2026 season file and name it 2019.
    """
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    page.reset_before_set = driver_mod.KIND_INPUT
    with pytest.raises(driver_mod.SessionLost, match="drifted before the fetch"):
        driver.prepare("raw", 2019, 5, "weighted")


def test_a_replaced_session_is_detected_even_when_the_inputs_look_right() -> None:
    """A new worker with the same inputs is still a different session, and the href it
    serves belongs to that one. The token is what says so."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    page.session = "s2"
    with pytest.raises(driver_mod.SessionLost):
        driver.assert_same_session()


def test_a_locked_download_control_refuses_to_run_rather_than_fetching_html() -> None:
    page = FakeShinyPage()
    page.link_text = driver_mod.LOCKED_TEXT
    driver = _driver_on(page)
    with pytest.raises(driver_mod.NotLoggedIn):
        driver.establish()


def test_a_login_that_lapses_mid_run_stops_the_run() -> None:
    """Not a per-file failure. Every remaining fetch would come back as the login page, and
    600 failures in a row is not a report anybody reads."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    driver.prepare("raw", 2019, 0, "weighted")
    page.link_text = driver_mod.LOCKED_TEXT
    with pytest.raises(driver_mod.NotLoggedIn):
        driver.fetch_payload()


def test_a_fresh_load_reads_2026_week_0_proj() -> None:
    """The premise the session-loss check rests on: this is what a reload leaves behind."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    assert driver.read_input(driver_mod.YEAR_INPUT) == "2026"
    assert driver.read_input(driver_mod.WEEK_INPUT) == "0"
    assert driver.read_input(driver_mod.KIND_INPUT) == "proj"


# ---------------------------------------------------------------------------------------
# Three premises the live app refuted, each now a gate. All three were in the handoff or in
# the first version of this driver, all three were wrong, and each would have broken the run
# in a way no CSV check could have caught.
# ---------------------------------------------------------------------------------------


def test_the_session_token_is_read_from_the_relative_href_the_app_actually_serves() -> None:
    """REFUTED PREMISE. The href is `session/<id>/download/...?w=...` -- relative, no worker
    prefix. Splitting on "/session/" found nothing and returned None for a live session,
    which would have made `assert_same_session` raise on every job in the run."""
    page = FakeShinyPage(session="f8ef99aeb854208d8b1abc8914a0276b")
    driver = _driver_on(page)
    href, _ = driver.download_control()
    assert href.startswith("session/"), href
    assert not href.startswith("/newApp/"), href
    assert driver.session_token() == "f8ef99aeb854208d8b1abc8914a0276b"


def test_the_absolute_href_form_still_reads_if_the_app_goes_back_to_it() -> None:
    """The fix is a regex over both forms, not a swap from one guess to the other."""
    assert driver_mod._SESSION_RE.search(
        "/newApp/_w_9/session/abc123/download/x?w=9"
    ).group(1) == "abc123"
    assert driver_mod._SESSION_RE.search("download/x?w=1") is None


def test_outputs_that_never_resolve_do_not_hold_the_driver(monkeypatch) -> None:
    """REFUTED PREMISE, and the expensive one.

    Five outputs on tabs this run never opens carry `.recalculating` forever, so
    "nothing is recalculating" is a predicate that can never be true on this app. The first
    version of this driver waited its full timeout on EVERY call -- measured at 45s against
    the live app, which over 600 files is about seven hours of doing nothing.
    """
    page = FakeShinyPage()
    driver = driver_mod.ShinyDriver(page, driver_mod.Settles(idle_timeout=5.0),
                                    log=lambda _m: None)
    driver.establish()
    assert len(driver._idle_baseline) == 5

    slept: list[float] = []
    monkeypatch.setattr(driver_mod.time, "sleep", lambda s: slept.append(s))
    driver.wait_idle()
    assert sum(slept) == 0.0, "a permanently stuck output held the driver"


def test_an_output_that_is_genuinely_working_does_hold_the_driver(monkeypatch) -> None:
    """The CONTROL. A baseline that swallowed everything would be the same as no check."""
    page = FakeShinyPage()
    driver = driver_mod.ShinyDriver(page, driver_mod.Settles(idle_timeout=1.0),
                                    log=lambda _m: None)
    driver.establish()
    page.working = ["projections_page-proj-projection_table"]

    slept: list[float] = []
    monkeypatch.setattr(driver_mod.time, "sleep", lambda s: slept.append(s))
    driver.wait_idle()
    assert sum(slept) > 0.0, "a working output did not hold the driver at all"
    assert driver.busy_beyond_baseline() == {"projections_page-proj-projection_table"}


def test_a_pending_message_queue_counts_as_busy() -> None:
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    assert driver.busy_beyond_baseline() == set()
    page.pending = 3
    assert driver.busy_beyond_baseline() == {"$pendingMessages=3"}


def test_the_idle_baseline_is_retaken_on_every_establish() -> None:
    """A re-established session is a different page, and its stuck set may differ."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    assert len(driver._idle_baseline) == 5
    page.stuck_outputs = ["accuracy_page-acc_ui"]
    driver.establish()
    assert driver._idle_baseline == frozenset({"accuracy_page-acc_ui"})


def test_the_driver_waits_for_a_populated_app_not_a_present_one() -> None:
    """REFUTED PREMISE, third of three. `wait_for_selector` on the download link returns
    long before Shiny has populated the widgets: a live headless session read year='',
    week='' and a download control whose text was the empty string, then went on to set
    inputs and fetch against it. Presence is not readiness."""
    page = FakeShinyPage()
    page.populated = False  # a cold worker, as the live headless session found
    driver = _driver_on(page)
    with pytest.raises(TimeoutError):
        driver.establish()
