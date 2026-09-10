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

from .tools.ffa_scrape import jobs as jobs_mod
from .tools.ffa_scrape import manifest as manifest_mod
from .tools.ffa_scrape import verify
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


def test_the_filename_is_deterministic() -> None:
    calls = [filename("raw", 2022, 9, "robust") for _ in range(50)]
    assert len(set(calls)) == 1


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
