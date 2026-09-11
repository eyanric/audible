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
from dataclasses import fields, replace
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

# The scraped corpus. Gitignored, so every gate that reads it skips where it is absent --
# which is CI, and is why nothing here may DEPEND on it for its meaning.
_CORPUS = Path(__file__).resolve().parent / "data" / "ffa_corpus"


def _corpus_present() -> bool:
    """At least one CSV, not merely the directory.

    `_CORPUS.exists()` is the wrong question and CI answered it on the first run this
    file was ever executed there: the DIRECTORY is tracked -- it carries README.md,
    COVERAGE.md and manifest.jsonl -- so it exists on a fresh clone while holding no data
    at all. Three gates therefore did not skip, and asserted against an empty corpus.
    """
    return any(_CORPUS.glob("ffa_*.csv"))


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def raw_csv(
    *,
    avg_type: str = "weighted",
    per_position: int = 60,
    positions: tuple[str, ...] = POSITIONS,
    header: tuple[str, ...] = RAW_HEADER,
    season_year: str = "NA",
    week_col: str = "NA",
) -> str:
    """A synthetic raw export. Shaped like the real thing where the checks look.

    `season_year` and `week_col` default to "NA" because that is exactly what 19 of the 213
    real raw files hold -- 2015 and early-2016 weekly -- and the scope check is
    presence-conditional for that reason. Gates that exercise the scope check pass real
    values, and one gate asserts the NA default is still faithful to the corpus.
    """
    lines = [",".join(_quote(column) for column in header)]
    pos_index = header.index("position")
    avg_index = header.index("avg_type") if "avg_type" in header else None
    year_index = header.index("season_year") if "season_year" in header else None
    week_index = header.index("week") if "week" in header else None
    for position in positions:
        for n in range(per_position):
            row = ["0"] * len(header)
            row[0] = _quote(f"{position} Player {n}")
            row[1] = _quote("KC")
            row[pos_index] = _quote(position)
            row[3] = _quote(str(10000 + n))
            if avg_index is not None:
                row[avg_index] = _quote(avg_type)
            if year_index is not None:
                row[year_index] = _quote(season_year)
            if week_index is not None:
                row[week_index] = _quote(week_col)
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
    reasons = verify_payload(payload, year=2019, kind="raw", week=0, avg="average")
    assert reasons, "a weighted payload was accepted for an average job"
    assert any(r.startswith("avg-type-mismatch") for r in reasons), reasons
    assert "weighted" in reasons[0] or any("weighted" in r for r in reasons)


def test_the_same_payload_asked_for_as_weighted_is_accepted() -> None:
    """The CONTROL. Without it a verifier that rejects everything would pass the gate above."""
    payload = raw_csv(avg_type="weighted")
    assert verify_payload(payload, year=2019, kind="raw", week=0, avg="weighted") == []


@pytest.mark.parametrize("wanted", ["weighted", "average", "robust"])
def test_each_aggregation_accepts_only_its_own(wanted: str) -> None:
    """Not just weighted-for-average. Every off-diagonal pair is rejected."""
    for held in ("weighted", "average", "robust"):
        reasons = verify_payload(raw_csv(avg_type=held), year=2019, kind="raw", week=0, avg=wanted)
        if held == wanted:
            assert reasons == [], f"{held} rejected for its own job: {reasons}"
        else:
            assert any(r.startswith("avg-type-mismatch") for r in reasons), (
                f"{held} accepted for a {wanted} job"
            )


def test_a_payload_holding_two_aggregations_is_rejected() -> None:
    """A mid-file switch is not a partial success. Neither half is what was asked for."""
    mixed = raw_csv(avg_type="weighted") + raw_csv(avg_type="robust").split("\n", 1)[1]
    reasons = verify_payload(mixed, year=2019, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("avg-type-mismatch") for r in reasons), reasons


def test_a_raw_payload_that_lost_its_aggregation_column_is_rejected() -> None:
    header = tuple(c for c in RAW_HEADER if c != "avg_type")
    payload = raw_csv(header=header)
    reasons = verify_payload(payload, year=2019, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("avg-type-column-absent") for r in reasons), reasons


def test_a_moved_aggregation_column_is_rejected_even_though_the_values_are_right() -> None:
    """Read-by-name would still find it. Stopping is the correct response to a schema change:
    the position claim this tool rests on is that avg_type is the FIFTH column."""
    header = ("avg_type",) + tuple(c for c in RAW_HEADER if c != "avg_type")
    payload = raw_csv(avg_type="average", header=header)
    reasons = verify_payload(payload, year=2019, kind="raw", week=0, avg="average")
    assert any(r.startswith("avg-type-column-moved") for r in reasons), reasons
    assert not any(r.startswith("avg-type-mismatch") for r in reasons), (
        "the values were correct; only the column moved"
    )


def test_a_proj_payload_is_accepted_without_an_aggregation_claim() -> None:
    """proj files carry no avg_type. They are unverifiable, not invalid."""
    assert verify_payload(proj_csv(), year=2019, kind="proj", week=0, avg="robust") == []
    assert inspect_csv(proj_csv()).sole_avg_type is None


def test_a_proj_payload_that_gained_an_aggregation_column_is_rejected() -> None:
    """If FFA ever adds one, the unverifiable-by-construction assumption is stale and the
    tool must be told rather than quietly keep treating proj as unverifiable."""
    reasons = verify_payload(raw_csv(), year=2019, kind="proj", week=0, avg="weighted")
    assert any(r.startswith("avg-type-column-unexpected") for r in reasons), reasons


# ---------------------------------------------------------------------------------------
# Position completeness. The Position dropdown filters the CHART only -- a download always
# carries all nine, so a file missing one is a defective download, not a narrower request.
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("dropped", POSITIONS)
def test_a_payload_missing_any_one_position_is_rejected(dropped: str) -> None:
    """Either as a missing core position or as partial IDP -- both are defective downloads.

    Dropping exactly one of the nine can never be legitimate: a scope without IDP has none
    of the three, not two.
    """
    kept = tuple(p for p in POSITIONS if p != dropped)
    payload = raw_csv(positions=kept)
    reasons = verify_payload(payload, year=2019, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("positions-") for r in reasons), reasons
    assert any(dropped in r for r in reasons), reasons


def test_the_nine_positions_agree_with_this_module_s_fixture_list() -> None:
    """Two constants agreeing. Named for that: the real-export claim is the gate below."""
    assert set(POSITIONS) == NINE_POSITIONS
    assert len(NINE_POSITIONS) == 9


@pytest.mark.skipif(not _corpus_present(), reason="gitignored corpus not on this machine")
def test_the_nine_positions_are_the_nine_a_real_export_holds() -> None:
    """Opens real exports. The gate above carried this name while comparing two hardcoded
    constants to each other -- it could not have noticed FFA adding a tenth position."""
    seen: set[str] = set()
    for path in sorted(_CORPUS.glob("ffa_raw_*_wk0_*.csv")):
        seen |= set(inspect_csv(path.read_text(encoding="utf-8")).positions)
    assert seen, "no season raw files to measure"
    assert seen == NINE_POSITIONS, seen ^ NINE_POSITIONS


def test_a_complete_payload_names_no_missing_position() -> None:
    """CONTROL for the parametrised gate above."""
    reasons = verify_payload(raw_csv(), year=2019, kind="raw", week=0, avg="weighted")
    assert not any(r.startswith("positions-missing") for r in reasons), reasons


# ---------------------------------------------------------------------------------------
# Row-count sanity and truncation.
# ---------------------------------------------------------------------------------------


def test_a_payload_truncated_mid_row_is_rejected() -> None:
    """A response cut short by a dropped connection. The last row has too few fields."""
    payload = raw_csv()
    truncated = payload[: len(payload) - 40]
    reasons = verify_payload(truncated, year=2019, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("ragged-rows") for r in reasons), reasons


def test_a_payload_truncated_to_a_stub_is_rejected_on_row_count() -> None:
    """A clean cut at a row boundary leaves no ragged row, so the floor is what catches it."""
    payload = raw_csv(per_position=2)
    reasons = verify_payload(payload, year=2019, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("row-count") for r in reasons), reasons


def test_a_header_only_payload_is_rejected() -> None:
    header_only = raw_csv().split("\n", 1)[0] + "\n"
    reasons = verify_payload(header_only, year=2019, kind="raw", week=0, avg="weighted")
    assert any(r.startswith("row-count") for r in reasons), reasons


def test_an_empty_payload_is_rejected_rather_than_raising() -> None:
    assert verify_payload("", year=2019, kind="raw", week=0, avg="weighted") == [
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
    assert verify_payload(payload, year=2019, kind="raw", week=5, avg="weighted") == []
    assert any(
        r.startswith("row-count")
        for r in verify_payload(payload, year=2019, kind="raw", week=0, avg="weighted")
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
        witness_sha256=None, positions={p: 1 for p in POSITIONS},
        fetched_at="2026-09-10T00:00:00Z",
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
        measured_avg_type=report.sole_avg_type, witness_sha256=None,
        positions=dict(report.positions), fetched_at="2026-09-10T12:00:00Z",
    )
    append_entry(path, entry)
    loaded = load_manifest(path)["ffa_raw_2019_wk0_average.csv"]
    assert loaded.sha256 == sha256_of(payload) and len(loaded.sha256) == 64
    assert loaded.bytes == len(payload.encode("utf-8"))
    assert loaded.rows == 9 * 60
    assert loaded.measured_avg_type == "average"
    assert set(loaded.positions) == NINE_POSITIONS
    assert loaded.fetched_at


def test_a_proj_manifest_entry_records_no_aggregation_claim(tmp_path: Path) -> None:
    """Through the MANIFEST, which is what the name promises. The previous body was a
    verbatim duplicate of an assertion in the verifier gates and never built an entry."""
    path = tmp_path / manifest_mod.MANIFEST_NAME
    payload = proj_csv()
    report = inspect_csv(payload)
    append_entry(
        path,
        ManifestEntry(
            file="ffa_proj_2019_wk0_average.csv", kind="proj", year=2019, week=0,
            avg="average", sha256=sha256_of(payload),
            bytes=len(payload.encode("utf-8")), rows=report.rows,
            measured_avg_type=report.sole_avg_type, witness_sha256="a" * 64,
            positions=dict(report.positions), fetched_at="2026-09-10T00:00:00Z",
        ),
    )
    entry = load_manifest(path)["ffa_proj_2019_wk0_average.csv"]
    assert entry.avg == "average", "the request is recorded"
    assert entry.measured_avg_type is None, "but no verification is claimed"
    assert entry.witness_sha256 == "a" * 64, "the witness is what stands behind it"


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
        _REAL.read_text(encoding="utf-8"), year=2019, kind="raw", week=0, avg="weighted"
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
        "sim/data/ffa_corpus/COVERAGE.md",
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
        self.settles = INSTANT
        self.prepared: list[tuple[str, int, int, str]] = []
        self.forced: list[bool] = []
        self.establishes = 0
        self._pending: object | None = None

    def prepare(
        self, kind: str, year: int, week: int, avg: str, *, force_settings_trip: bool = False
    ) -> None:
        self.prepared.append((kind, year, week, avg))
        self.forced.append(force_settings_trip)
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
    fake = FakeDriver(script)
    with pytest.raises(driver_mod.SessionLost):
        runner.run_jobs(
            fake,  # type: ignore[arg-type]
            jobs,
            data_dir=tmp_path,
            manifest_path=tmp_path / manifest_mod.MANIFEST_NAME,
            now=lambda: "2026-09-10T00:00:00+00:00",
            log=lambda _msg: None,
        )
    # THE CAP, not merely that it eventually raises. Six jobs at two attempts each leave
    # room for twelve consecutive recoveries, so "it raised" stayed green for any cap from
    # 1 to 11. It re-establishes exactly MAX times and raises on the next.
    assert fake.establishes == runner.MAX_CONSECUTIVE_RECOVERIES, fake.establishes


def test_the_runner_forwards_every_job_its_own_aggregation(tmp_path: Path) -> None:
    """The RUNNER never substitutes an aggregation, in job order.

    Named for what it asserts. It used to be called `..._re_sets_the_aggregation_after_the_
    year` and its docstring said "Behaviour 1 has no fast path" -- but `ShinyDriver.prepare`
    explicitly HAS one (`force_settings_trip or self._effective_avg != avg`), and this gate
    runs against `FakeDriver`, whose prepare only records its arguments. The driver-level
    claim is `test_a_weighted_job_after_a_robust_one_in_the_SAME_year_still_gets_weighted`.
    """
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

# Built from the dataclass fields rather than written out, so a settle added later cannot
# quietly keep its production default here. The hand-written version missed `after_load`
# (6.0s, paid on every `establish()`) and every driver gate slept through it -- twelve
# seconds for the two that establish twice. The suite still passed, so nothing said so; it
# surfaced only because the mutation sweep, which runs the suite once per mutation, slowed
# to eleven minutes a mutation.
INSTANT = replace(
    driver_mod.Settles(**{f.name: 0.0 for f in fields(driver_mod.Settles)}),
    # Not pauses: a timeout of zero would make `wait_idle` a no-op and a readiness timeout
    # of zero would fail every establish.
    idle_timeout=0.05,
    stuck_after=0.01,
    ready_timeout=5.0,
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
        # A Shiny modal. Measured live mid-run: data-backdrop="static" and
        # data-keyboard="false", so it cannot be dismissed by clicking away or by Escape,
        # and its backdrop intercepts pointer events -- a real click just times out.
        self.modal: str | None = None
        self.modal_dismissible = True
        self.dismissals = 0
        self.evaluate_href_override: dict | None = None

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

    def click(self, selector: str, **_kwargs: object) -> None:
        if self.modal is not None:
            # What Playwright actually does: retries until the timeout, then raises.
            raise TimeoutError(
                "Page.click: Timeout exceeded -- #shiny-modal intercepts pointer events"
            )
        tab = selector.split('"')[1]
        self.calls.append(f"click:{tab}")
        if self.tab == "tab_settings" and tab == "tab_proj":
            self.effective_avg = self.inputs[driver_mod.AVG_INPUT]  # behaviour 2
        self.tab = tab

    def evaluate(self, script: str, arg: object = None) -> object:
        if script is driver_mod._MODAL_PROBE_JS:
            # READ ONLY. The probe must never dismiss, or "did it close?" becomes a second
            # dismissal and the driver reports on a modal it just actuated.
            if self.modal is None:
                return {"present": False, "text": None, "dismissible": False}
            return {
                "present": True,
                "text": self.modal,
                "dismissible": self.modal_dismissible,
            }
        if script is driver_mod._MODAL_DISMISS_JS:
            if self.modal is not None and self.modal_dismissible:
                self.modal = None
                self.dismissals += 1
                return {"clicked": True, "via": '[data-dismiss="modal"]'}
            return {"clicked": False, "via": None}
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
            if self.evaluate_href_override is not None:
                return self.evaluate_href_override
            # MEASURED: relative, no worker prefix. The absolute form the driver was first
            # written against does not occur.
            return {
                "found": True,
                "href": (
                    f"session/{self.session}/download/"
                    "projections_page-proj-download_projections-download?w=0f0f0f0f"
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
        """A payload that names its own scope, like 194 of the 213 real raw files do.

        It used to serve `raw_csv(avg_type=...)` with the helper's NA defaults, so every
        payload the model produced fell in the 19-file minority where `verify.py`'s scope
        check is switched off by construction -- and every driver-level
        `verify_payload(...) == []` was insensitive to its own `year=` and `week=`
        arguments. The check was there; nothing at this level could tell whether it worked.
        """
        if self.inputs[driver_mod.KIND_INPUT] == "proj":
            return proj_csv()
        return raw_csv(
            avg_type=self.effective_avg,
            season_year=self.inputs[driver_mod.YEAR_INPUT],
            week_col=self.inputs[driver_mod.WEEK_INPUT],
        )


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
        assert verify_payload(payload.text, year=2019, kind="raw", week=0, avg=avg) == [], avg


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
    reasons = verify_payload(payload.text, year=2019, kind="raw", week=0, avg="average")
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
    page = FakeShinyPage(session="0123456789abcdef0123456789abcdef")
    driver = _driver_on(page)
    href, _ = driver.download_control()
    assert href.startswith("session/"), href
    assert not href.startswith("/newApp/"), href
    assert driver.session_token() == "0123456789abcdef0123456789abcdef"


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
    driver = driver_mod.ShinyDriver(
        page, replace(INSTANT, idle_timeout=5.0), log=lambda _m: None
    )
    driver.establish()
    assert len(driver._idle_baseline) == 5

    slept: list[float] = []
    monkeypatch.setattr(driver_mod.time, "sleep", lambda s: slept.append(s))
    driver.wait_idle()
    assert sum(slept) == 0.0, "a permanently stuck output held the driver"


def test_an_output_that_is_genuinely_working_does_hold_the_driver(monkeypatch) -> None:
    """The CONTROL. A baseline that swallowed everything would be the same as no check."""
    page = FakeShinyPage()
    # stuck_after must stay LARGE here: INSTANT sets it to 0.01, which would reclassify the
    # working output as stuck on the first poll and make this control vacuous.
    driver = driver_mod.ShinyDriver(
        page, replace(INSTANT, idle_timeout=1.0, stuck_after=10.0), log=lambda _m: None
    )
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


def test_an_output_that_never_resolves_joins_the_stuck_set_and_stops_costing(
    monkeypatch,
) -> None:
    """REFUTED PREMISE, fourth of five. A baseline taken at establish time covers only what
    was pending on the Projections tab; the first click to Settings renders outputs that
    were never requested before, and some of those never resolve either. Measured against
    the live app: every Settings trip sat out the full idle timeout again.

    So the stuck set GROWS. The first wait pays `stuck_after`; every later one pays nothing.
    """
    page = FakeShinyPage()
    settles = replace(INSTANT, idle_timeout=30.0, stuck_after=4.0)
    driver = driver_mod.ShinyDriver(page, settles, log=lambda _m: None)
    driver.establish()

    clock = {"t": 1000.0}
    monkeypatch.setattr(driver_mod.time, "time", lambda: clock["t"])
    monkeypatch.setattr(driver_mod.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))

    # A Settings output appears and never finishes.
    page.working = ["settings_page-some_output_that_never_finishes"]
    start = clock["t"]
    driver.wait_idle()
    first_cost = clock["t"] - start
    assert 4.0 <= first_cost < 30.0, first_cost
    assert "settings_page-some_output_that_never_finishes" in driver._idle_baseline

    start = clock["t"]
    driver.wait_idle()
    assert clock["t"] - start == 0.0, "a known-stuck output was waited on again"


def test_an_output_that_finishes_in_time_never_joins_the_stuck_set(monkeypatch) -> None:
    """CONTROL. A stuck set that grew on everything would be the same as no check at all."""
    page = FakeShinyPage()
    settles = replace(INSTANT, idle_timeout=30.0, stuck_after=4.0)
    driver = driver_mod.ShinyDriver(page, settles, log=lambda _m: None)
    driver.establish()

    clock = {"t": 1000.0}
    monkeypatch.setattr(driver_mod.time, "time", lambda: clock["t"])

    def tick(seconds: float) -> None:
        clock["t"] += seconds
        if clock["t"] >= 1002.0:
            page.working = []  # it finished, well inside stuck_after

    page.working = ["projections_page-proj-projection_table"]
    monkeypatch.setattr(driver_mod.time, "sleep", tick)
    driver.wait_idle()
    assert "projections_page-proj-projection_table" not in driver._idle_baseline
    assert len(driver._idle_baseline) == 5


def test_a_pending_message_queue_never_joins_the_stuck_set(monkeypatch) -> None:
    """It is a count, not an output id -- adding `$pendingMessages=3` to the stuck set would
    mean a queue of exactly 3 was ignored forever and any other length was not."""
    page = FakeShinyPage()
    settles = replace(INSTANT, idle_timeout=12.0, stuck_after=2.0)
    driver = driver_mod.ShinyDriver(page, settles, log=lambda _m: None)
    driver.establish()

    clock = {"t": 1000.0}
    monkeypatch.setattr(driver_mod.time, "time", lambda: clock["t"])
    monkeypatch.setattr(driver_mod.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    page.pending = 3
    driver.wait_idle()
    assert not any(name.startswith("$") for name in driver._idle_baseline)


def test_a_weighted_job_after_a_robust_one_in_the_SAME_year_still_gets_weighted() -> None:
    """REFUTED PREMISE, and the one the live probe caught in this driver.

    "Changing the year resets the aggregation" is true. The corollary is not: setting the
    year to the value it already holds changes nothing, so it resets nothing. A weighted job
    that follows a robust job in the same year was relying on a year change that never
    happened, and the live app served `robust` under a `weighted` request. Measured:

        weekly-2019-wk5: asked for 'weighted', file holds ['robust']

    The verifier caught it, which is what the verifier is for -- but a run where a third of
    the jobs fail and retry is not a run. The driver now tracks the EFFECTIVE aggregation
    and takes the Settings trip whenever it is not already what the job wants.

    The earlier ordering gate did not catch this because it walked weighted -> average ->
    robust: the weighted job came first, right after a real year change.
    """
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()

    driver.prepare("raw", 2019, 0, "robust")
    assert inspect_csv(driver.fetch_payload().text).sole_avg_type == "robust"

    driver.prepare("raw", 2019, 5, "weighted")  # same year -- no reset comes for free
    payload = driver.fetch_payload()
    assert verify_payload(payload.text, year=2019, kind="raw", week=5, avg="weighted") == []
    assert inspect_csv(payload.text).sole_avg_type == "weighted"


def test_a_run_of_weighted_jobs_in_one_year_pays_for_at_most_one_settings_trip() -> None:
    """The cost model survives the fix. Seventeen weekly jobs in a season take one trip
    between them at worst, not seventeen -- which is the whole reason stage 1 is cheap."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    driver.prepare("raw", 2019, 0, "robust")

    trips = []
    for week in range(1, 18):
        page.calls.clear()
        driver.prepare("raw", 2019, week, "weighted")
        assert inspect_csv(driver.fetch_payload().text).sole_avg_type == "weighted"
        trips.append("click:tab_settings" in page.calls)
    assert sum(trips) <= 1, f"{sum(trips)} settings trips across 17 weighted jobs"


def test_a_year_change_still_buys_the_weighted_job_its_reset_for_free() -> None:
    """The optimisation is not abandoned, only made conditional."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    driver.prepare("raw", 2019, 0, "robust")

    page.calls.clear()
    driver.prepare("raw", 2020, 0, "weighted")  # a REAL year change
    assert "click:tab_settings" not in page.calls, page.calls
    assert inspect_csv(driver.fetch_payload().text).sole_avg_type == "weighted"


def test_a_re_established_session_does_not_trust_a_remembered_aggregation() -> None:
    """After a reload the app is weighted again, but believing that without CHECKING is the
    same class of assumption that caused all of this. Unknown means take the trip.

    The job here is 2026 -- the year a reload already leaves behind -- so no year change
    occurs and nothing tells the driver the aggregation was reset. That is the only case
    where the remembered value would have to be trusted, and it is not.
    """
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    driver.prepare("raw", 2019, 0, "robust")
    driver.establish()
    assert driver._effective_avg is None

    page.calls.clear()
    driver.prepare("raw", 2026, 0, "weighted")
    assert "click:tab_settings" in page.calls, page.calls


def test_the_retry_forces_the_settings_trip_the_first_attempt_judged_unnecessary(
    tmp_path: Path,
) -> None:
    """A wrong aggregation is the failure the retry exists for, so the retry must not repeat
    the judgement that caused it. Slower alone would not help if the first attempt skipped
    the trip on a belief that was wrong."""
    job = Job(kind="raw", year=2019, week=5, avg="weighted")
    fake, result = _run(
        {job.filename: [raw_csv(avg_type="robust"), raw_csv(avg_type="weighted")]},
        [job],
        tmp_path,
    )
    assert result.completed == [job.filename]
    assert fake.forced == [False, True], fake.forced


# ---------------------------------------------------------------------------------------
# IDP is a property of the SCOPE, not evidence of a good download. Measured live:
#
#   [1/6] ffa_raw_2015_wk1_weighted.csv
#       rejected: positions-missing: ['DB', 'DL', 'LB'] absent
#                 (have ['DST', 'K', 'QB', 'RB', 'TE', 'WR'])
#
# The handoff's "downloads always carry all nine positions" was verified on a SEASON file in
# 2019 and does not generalise. Rejecting 2015 weekly would have thrown away good offensive
# data over a position group the app does not project for that scope.
# ---------------------------------------------------------------------------------------

CORE_ONLY: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DST")


def test_a_weekly_file_with_no_idp_at_all_is_kept() -> None:
    """2015 week 1, as measured. Six positions, no IDP, and nothing wrong with it."""
    payload = raw_csv(positions=CORE_ONLY, per_position=40)
    assert verify_payload(payload, year=2019, kind="raw", week=1, avg="weighted") == []


def test_a_file_missing_a_CORE_position_is_still_rejected() -> None:
    """The check that catches a defective download did not go away, it got narrower."""
    for dropped in CORE_ONLY:
        kept = tuple(p for p in CORE_ONLY if p != dropped)
        reasons = verify_payload(
            raw_csv(positions=kept, per_position=40), year=2019, kind="raw", week=1, avg="weighted"
        )
        assert any(r.startswith("positions-missing") for r in reasons), (dropped, reasons)


@pytest.mark.parametrize("partial", [("DL",), ("DL", "LB"), ("DB",), ("LB", "DB")])
def test_a_file_with_SOME_idp_is_rejected(partial: tuple[str, ...]) -> None:
    """All-or-nothing. A scope either has IDP or it does not; two of the three is not a
    narrower file, it is a broken one -- and that is the shape a truncated download takes."""
    payload = raw_csv(positions=(*CORE_ONLY, *partial), per_position=40)
    reasons = verify_payload(payload, year=2019, kind="raw", week=1, avg="weighted")
    assert any(r.startswith("positions-partial-idp") for r in reasons), reasons


def test_a_file_with_every_idp_position_is_kept() -> None:
    """CONTROL for the rule above."""
    payload = raw_csv(positions=POSITIONS, per_position=40)
    assert verify_payload(payload, year=2019, kind="raw", week=1, avg="weighted") == []


def test_the_core_and_idp_sets_partition_the_nine() -> None:
    assert verify.CORE_POSITIONS | verify.IDP_POSITIONS == NINE_POSITIONS
    assert not (verify.CORE_POSITIONS & verify.IDP_POSITIONS)
    assert len(verify.CORE_POSITIONS) == 6
    assert len(verify.IDP_POSITIONS) == 3


def test_a_season_file_with_all_nine_is_still_the_normal_case() -> None:
    """Nothing about the weekly finding relaxes what a season file is expected to hold; the
    manifest records the positions either way, so a reader can tell them apart."""
    report = inspect_csv(raw_csv())
    assert set(report.positions) == NINE_POSITIONS
    assert verify_payload(raw_csv(), year=2019, kind="raw", week=0, avg="weighted") == []


def test_no_offline_gate_sleeps_through_a_production_settle() -> None:
    """The gates are offline; a gate that WAITS is measuring nothing but the clock.

    `INSTANT` missed `after_load` when it was written out by hand, so every driver gate
    paid its 6.0s inside `establish()` and the two that establish twice took twelve
    seconds each. The suite stayed green throughout -- slowness is not a failure -- and it
    surfaced only because the mutation sweep runs the suite once per mutation and went to
    eleven minutes a mutation.

    Building `INSTANT` from the dataclass fields is what fixes it. This gate is what says
    a hand-written one would not be accepted back.
    """
    pauses = [
        f.name
        for f in fields(driver_mod.Settles)
        if f.name == "action" or f.name.startswith("after_")
    ]
    assert pauses, "no pause fields found; this gate has stopped checking anything"
    assert "after_load" in pauses, "the field that caused this is no longer covered"
    for name in pauses:
        assert getattr(INSTANT, name) == 0.0, f"INSTANT.{name} is a real sleep"


def test_the_instant_settles_still_let_the_driver_work() -> None:
    """CONTROL: zeroing everything must not make the gates vacuous."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    driver.prepare("raw", 2019, 0, "average")
    assert inspect_csv(driver.fetch_payload().text).sole_avg_type == "average"


def test_this_module_never_builds_a_settles_with_production_defaults() -> None:
    """The mechanism, not just the outcome.

    Zeroing `INSTANT` fixed the driver gates; five stuck-set gates still built their own
    `Settles(idle_timeout=..., stuck_after=...)` and inherited `after_load=6.0` from the
    production defaults, so they went on sleeping. Every construction in this file must
    derive from `INSTANT`, and the only bare one allowed is the line that builds it.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    bare = [
        line.strip()
        for line in source.splitlines()
        if "driver_mod.Settles(" in line and "f.name: 0.0 for f in fields" not in line
    ]
    assert bare == [], f"these build a Settles with production defaults: {bare}"


def test_wait_idle_paces_itself_even_while_the_stuck_set_is_growing(monkeypatch) -> None:
    """A latent SPIN, found by a mutation rather than by review.

    `wait_idle` used to `continue` after growing the stuck set, skipping the sleep. That is
    safe only while `newly_stuck` eventually stops being produced -- and
    `busy_beyond_baseline` adds the `$pendingMessages` marker AFTER subtracting the
    baseline, so a marker can never be subtracted out. A mutation that let markers into the
    stuck set made `newly_stuck` non-empty on every poll and the loop re-entered forever
    without pacing. Under the frozen clock these gates use, that hung the entire suite for
    nine minutes before it was noticed.

    Against the live app the real clock still bounds the loop at `idle_timeout`, so the
    production symptom is a CPU spin rather than a hang. Either way the loop must pace.

    Here a fresh output appears on every poll, so the stuck set grows every time. The gate
    is simply that this RETURNS.
    """
    page = FakeShinyPage()
    settles = replace(INSTANT, idle_timeout=10.0, stuck_after=0.0)
    driver = driver_mod.ShinyDriver(page, settles, log=lambda _m: None)
    driver.establish()

    clock = {"t": 1000.0}
    polls = {"n": 0}
    monkeypatch.setattr(driver_mod.time, "time", lambda: clock["t"])
    monkeypatch.setattr(
        driver_mod.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s)
    )

    original = page.evaluate

    def evaluate(script: str, arg: object = None) -> object:
        if script is driver_mod._BUSY_JS:
            polls["n"] += 1
            # A NEW never-resolving output every single poll.
            return {"busy": [f"output_{polls['n']}"], "pending": 0}
        return original(script, arg)

    monkeypatch.setattr(page, "evaluate", evaluate)

    driver.wait_idle()  # the gate: this returns at all

    # And it returned by running out the clock, not by luck.
    assert clock["t"] >= 1000.0 + settles.idle_timeout
    assert polls["n"] <= settles.idle_timeout / 0.25 + 2, (
        f"{polls['n']} polls for a {settles.idle_timeout}s window -- the loop is not pacing"
    )


# ---------------------------------------------------------------------------------------
# THE WITNESS. A proj export carries no avg_type column, so on its own the aggregation it
# was fetched under cannot be confirmed from its own bytes -- the handoff calls proj files
# unverifiable and says to prefer raw.
#
# That is true of a proj file fetched ALONE. Fetch the raw file from the same session state
# first, read its fifth column, and the aggregation is witnessed: the proj fetch that
# follows differs in exactly one input. 27 otherwise-unverifiable files for about fourteen
# minutes of extra fetching.
# ---------------------------------------------------------------------------------------


def _witness_driver(page: FakeShinyPage) -> driver_mod.ShinyDriver:
    return driver_mod.ShinyDriver(page, INSTANT, log=lambda _m: None)


def test_a_proj_job_fetches_a_raw_witness_first(tmp_path: Path) -> None:
    page = FakeShinyPage()
    driver = _witness_driver(page)
    driver.establish()

    job = Job(kind="proj", year=2019, week=0, avg="robust")
    result = runner.run_jobs(
        driver, [job], data_dir=tmp_path,
        manifest_path=tmp_path / manifest_mod.MANIFEST_NAME,
        now=lambda: "2026-09-10T00:00:00+00:00", log=lambda _m: None,
    )
    assert result.completed == [job.filename], result.failed
    entry = load_manifest(tmp_path / manifest_mod.MANIFEST_NAME)[job.filename]

    # The proj file itself still says nothing about its aggregation...
    assert entry.measured_avg_type is None
    # ...and the raw file fetched from the same state is what stands behind it. The witness
    # names the scope it was fetched for, which is the whole reason it can vouch: a proj
    # export has no season_year or week column of its own.
    assert entry.witness_sha256 == sha256_of(
        raw_csv(avg_type="robust", season_year="2019", week_col="0")
    )


def test_a_proj_job_is_rejected_when_its_witness_holds_the_wrong_aggregation(
    tmp_path: Path,
) -> None:
    """THE point of the witness, and a defect that is otherwise undetectable.

    The app is made to serve `weighted` regardless. The proj payload is byte-identical to a
    correct one -- there is nothing in it to catch -- and the job is rejected anyway,
    because the raw file fetched from the same session state said `weighted`.
    """
    page = FakeShinyPage()
    page.effective_avg = "weighted"
    # Pin it: the Settings round trip no longer takes.
    page.click = lambda selector, **_kw: None  # type: ignore[method-assign]
    driver = _witness_driver(page)
    driver.establish()

    job = Job(kind="proj", year=2019, week=0, avg="average")
    result = runner.run_jobs(
        driver, [job], data_dir=tmp_path,
        manifest_path=tmp_path / manifest_mod.MANIFEST_NAME,
        now=lambda: "2026-09-10T00:00:00+00:00", log=lambda _m: None,
    )
    assert result.completed == []
    assert not (tmp_path / job.filename).exists(), "an unwitnessed proj file reached disk"
    reasons = result.failed[0][1]
    assert any(r.startswith("witness-avg-type-mismatch") for r in reasons), reasons


def test_a_raw_job_needs_no_witness(tmp_path: Path) -> None:
    """CONTROL. A raw file vouches for itself; paying for a witness would double the run."""
    page = FakeShinyPage()
    driver = _witness_driver(page)
    driver.establish()

    job = Job(kind="raw", year=2019, week=0, avg="robust")
    runner.run_jobs(
        driver, [job], data_dir=tmp_path,
        manifest_path=tmp_path / manifest_mod.MANIFEST_NAME,
        now=lambda: "2026-09-10T00:00:00+00:00", log=lambda _m: None,
    )
    entry = load_manifest(tmp_path / manifest_mod.MANIFEST_NAME)[job.filename]
    assert entry.witness_sha256 is None
    assert entry.measured_avg_type == "robust"


def test_the_witness_and_the_proj_file_differ_in_exactly_one_input() -> None:
    """The whole argument rests on this: if anything else changed between the two fetches,
    the witness would be vouching for a different request."""
    page = FakeShinyPage()
    driver = _witness_driver(page)
    driver.establish()
    driver.prepare("raw", 2021, 0, "average")
    before = dict(page.inputs)
    driver.switch_kind("proj", 2021, 0)
    after = dict(page.inputs)
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {driver_mod.KIND_INPUT}, changed


def test_a_manifest_written_before_witnessing_existed_still_loads(tmp_path: Path) -> None:
    """Backward compatibility, because 101 weekly files were already on disk when the
    witness was added. A line with no witness_sha256 reads as None, not as an error."""
    path = tmp_path / manifest_mod.MANIFEST_NAME
    path.write_text(
        json.dumps(
            {
                "file": "ffa_raw_2019_wk0_weighted.csv", "kind": "raw", "year": 2019,
                "week": 0, "avg": "weighted", "sha256": "0" * 64, "bytes": 10,
                "rows": 5, "measured_avg_type": "weighted", "positions": {},
                "fetched_at": "2026-09-10T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    entry = load_manifest(path)["ffa_raw_2019_wk0_weighted.csv"]
    assert entry.witness_sha256 is None


# ---------------------------------------------------------------------------------------
# MODALS. Measured mid-run, eight files into stage 2, and seen by neither the handoff nor
# the probe: a Shiny modal appears with data-backdrop="static" and data-keyboard="false",
# so it cannot be dismissed by clicking away or by Escape, and its backdrop intercepts
# pointer events. Playwright retried the tab click for thirty seconds and the run died.
# ---------------------------------------------------------------------------------------


def test_a_modal_blocks_a_real_click_the_way_the_live_one_did() -> None:
    """The model earns the gates below by reproducing the failure first."""
    page = FakeShinyPage()
    page.modal = "Your session is about to expire."
    with pytest.raises(TimeoutError):
        page.click('a[data-value="tab_proj"]')


def test_a_modal_is_read_and_closed_before_the_click() -> None:
    """A modal is the app trying to say something. Log it, close it, carry on."""
    page = FakeShinyPage()
    logged: list[str] = []
    driver = driver_mod.ShinyDriver(page, INSTANT, log=logged.append)
    driver.establish()
    page.modal = "Your session is about to expire."

    driver.click_tab("tab_proj")  # would have raised TimeoutError without clear_modal
    assert page.modal is None
    assert any("about to expire" in line for line in logged), logged


def test_a_modal_with_no_dismiss_control_stops_the_run_and_says_what_it_said() -> None:
    """A run that cannot proceed must name the reason. Thirty seconds of Playwright retry
    log naming a div is not that."""
    page = FakeShinyPage()
    page.modal = "Subscription expired. Renew to continue."
    page.modal_dismissible = False
    driver = driver_mod.ShinyDriver(page, INSTANT, log=lambda _m: None)
    driver.establish()
    with pytest.raises(driver_mod.ModalBlocked, match="Subscription expired"):
        driver.click_tab("tab_proj")


def test_no_modal_costs_nothing_and_says_nothing() -> None:
    """CONTROL. A handler that fired on every click would fill the log with noise."""
    page = FakeShinyPage()
    logged: list[str] = []
    driver = driver_mod.ShinyDriver(page, INSTANT, log=logged.append)
    driver.establish()
    logged.clear()
    assert driver.clear_modal() is None
    driver.click_tab("tab_proj")
    assert not any("modal" in line for line in logged), logged


def test_a_modal_that_reappears_immediately_is_not_treated_as_closed() -> None:
    """Clicking dismiss is not the same as the modal being gone. A modal that Shiny puts
    straight back is still blocking, and pretending otherwise loops forever."""
    page = FakeShinyPage()

    page.modal = "Please wait..."
    original = page.evaluate

    def evaluate(script: str, arg: object = None) -> object:
        result = original(script, arg)
        if script is driver_mod._MODAL_DISMISS_JS:
            page.modal = "Please wait..."  # Shiny puts it straight back
        return result

    page.evaluate = evaluate  # type: ignore[method-assign]
    driver = driver_mod.ShinyDriver(page, INSTANT, log=lambda _m: None)
    with pytest.raises(driver_mod.ModalBlocked, match="still up after dismissing"):
        driver.clear_modal()


# ---------------------------------------------------------------------------------------
# THE SCOPE CHECK. Found by adversarial review, not by this session: `verify_payload` took
# no `year` and never read the payload's own `season_year`, so a payload for the WRONG
# SEASON passed with zero reasons and was written under the requested year's clean name.
#
# It is the same shape as the defect this tool exists for, on a different axis, and the
# avg_type check provably cannot see it: a real year change ALSO resets the aggregation to
# weighted, so a stale payload and the wanted one both read `weighted`. Positions are
# complete in both, both clear the row floor, so nothing else fires either.
#
# Measured over 213 raw files: 194 carry a populated season_year and week agreeing with
# their filename exactly, 0 disagree, 19 hold NA in both.
# ---------------------------------------------------------------------------------------


def test_a_payload_for_the_wrong_season_is_rejected() -> None:
    """The reviewer's scenario, exactly: 2019 bytes offered for a 2020 job."""
    payload = raw_csv(season_year="2019", week_col="0")
    assert verify_payload(payload, kind="raw", year=2019, week=0, avg="weighted") == []
    reasons = verify_payload(payload, kind="raw", year=2020, week=0, avg="weighted")
    assert any(r.startswith("season-mismatch") for r in reasons), reasons


def test_the_aggregation_check_cannot_see_a_wrong_season() -> None:
    """Why the scope check had to be added rather than relied upon elsewhere.

    A year change resets the aggregation to weighted, so a stale payload and the wanted one
    carry the SAME avg_type. Every other check passes too. Without the season check this
    payload is indistinguishable from a correct one.
    """
    stale = raw_csv(avg_type="weighted", season_year="2019", week_col="0")
    reasons = verify_payload(stale, kind="raw", year=2020, week=0, avg="weighted")
    assert [r.split(":")[0] for r in reasons] == ["season-mismatch"], reasons


def test_a_payload_for_the_wrong_week_is_rejected() -> None:
    """The weekly stage fetches 17 consecutive jobs differing only in the week dropdown,
    with no Settings trip. A download handler one step behind the widget writes week N-1's
    bytes under week N's name, byte-identical to the file written one job earlier."""
    payload = raw_csv(season_year="2021", week_col="4", per_position=30)
    assert verify_payload(payload, kind="raw", year=2021, week=4, avg="weighted") == []
    reasons = verify_payload(payload, kind="raw", year=2021, week=5, avg="weighted")
    assert any(r.startswith("week-mismatch") for r in reasons), reasons


def test_a_season_payload_offered_as_weekly_is_rejected() -> None:
    """And the reverse. The row floors cannot tell these apart -- 113 of 186 weekly files
    hold MORE rows than the smallest season file."""
    season = raw_csv(season_year="2019", week_col="0")
    reasons = verify_payload(season, kind="raw", year=2019, week=9, avg="weighted")
    assert any(r.startswith("week-mismatch") for r in reasons), reasons

    weekly = raw_csv(season_year="2019", week_col="9", per_position=30)
    reasons = verify_payload(weekly, kind="raw", year=2019, week=0, avg="weighted")
    assert any(r.startswith("week-mismatch") for r in reasons), reasons


def test_a_payload_that_names_no_season_is_still_kept() -> None:
    """PRESENCE-CONDITIONAL, like IDP. 19 real files hold NA in both columns and are not
    defective for it; requiring the column would discard every 2015 weekly file."""
    payload = raw_csv(season_year="NA", week_col="NA")
    assert verify_payload(payload, kind="raw", year=2020, week=7, avg="weighted") == []


def test_a_payload_with_two_seasons_in_it_is_rejected() -> None:
    """A frame stitched across a year change is not a partial success."""
    first = raw_csv(season_year="2019", week_col="0")
    second = raw_csv(season_year="2020", week_col="0").split("\n", 1)[1]
    reasons = verify_payload(first + second, kind="raw", year=2019, week=0, avg="weighted")
    assert any(r.startswith("season-mismatch") for r in reasons), reasons


def test_the_row_floors_do_not_pretend_to_separate_season_from_weekly() -> None:
    """The docstring used to claim season files are "far larger" than weekly ones, and that
    is measurably false -- which is exactly why nobody added the check above.

    Season raw spans 819..2236 rows and weekly raw spans 521..1856. A weekly-sized payload
    clears the SEASON floor, so the floors provide no scope discrimination whatsoever.
    """
    weekly_sized = raw_csv(per_position=60)  # 540 rows, a realistic weekly count
    assert verify_payload(weekly_sized, kind="raw", year=2019, week=0, avg="weighted") == []
    assert verify.min_rows_for("raw", 0) < 540


def test_an_unknown_kind_returns_a_reason_rather_than_raising() -> None:
    """It used to raise KeyError from min_rows_for before the reason could be produced, so
    a typo'd kind killed the run with a traceback out of run_jobs -- which catches only
    SessionLost and NotLoggedIn -- instead of rejecting one file with a logged reason.
    That contradicted this module's own stated contract."""
    reasons = verify_payload(raw_csv(), kind="projections", year=2019, week=0, avg="weighted")
    assert reasons == ["unknown-kind: 'projections'"]


def test_the_na_fixture_default_matches_what_real_files_hold() -> None:
    """`raw_csv()` writes 'NA' and `_ABSENT` contains 'NA', so asserting the set is empty is
    a tautology over the test's own helper. What is NOT a tautology is that real files hold
    both shapes -- so this reads them."""
    report = inspect_csv(raw_csv())
    assert report.season_years == frozenset()
    populated = inspect_csv(raw_csv(season_year="2022", week_col="6"))
    assert populated.season_years == frozenset({"2022"})
    assert populated.weeks == frozenset({"6"})


@pytest.mark.skipif(not _corpus_present(), reason="gitignored corpus not on this machine")
def test_both_scope_shapes_really_occur_in_the_corpus() -> None:
    """The presence-conditional rule exists because BOTH shapes are real. If every file
    named its scope the rule would be needless laxity; if none did it would be dead code."""
    named = unnamed = 0
    for path in sorted(_CORPUS.glob("ffa_raw_*.csv")):
        if inspect_csv(path.read_text(encoding="utf-8")).season_years:
            named += 1
        else:
            unnamed += 1
    assert named > 0, "no file names its scope; the check is dead code"
    assert unnamed > 0, "every file names its scope; the NA branch is needless laxity"


@pytest.mark.skipif(not _corpus_present(), reason="gitignored corpus not on this machine")
def test_every_file_in_the_corpus_passes_the_scope_check() -> None:
    """The check was added after 231 files were already fetched. This says none of them
    were wrong -- the hole was open, and nothing had fallen through it."""
    from .tools.ffa_scrape.naming import parse_filename as _parse

    checked = failures = 0
    for path in sorted(_CORPUS.glob("ffa_*.csv")):
        kind, year, week, avg = _parse(path.name)
        reasons = verify_payload(
            path.read_text(encoding="utf-8"), kind=kind, year=year, week=week, avg=avg
        )
        checked += 1
        if reasons:
            failures += 1
    assert checked > 0, "corpus directory is present but empty"
    assert failures == 0, f"{failures} of {checked} corpus files fail verification"


# ---------------------------------------------------------------------------------------
# Findings from the adversarial review, each now a gate. None of these was found by writing
# the code or by running it; all of them were found by an agent trying to break it.
# ---------------------------------------------------------------------------------------


def test_appending_after_a_torn_tail_does_not_swallow_the_next_line(tmp_path: Path) -> None:
    """load_manifest tolerates a half-written final line, but appending straight onto one
    CONCATENATES with it: the good new line is swallowed into an unparseable one, and as
    soon as a further line follows, that corruption is no longer last and load_manifest
    raises on it -- turning one lost file into a manifest that will not load at all."""
    path = tmp_path / manifest_mod.MANIFEST_NAME
    jobs = jobs_mod.STAGES["season-raw"][:3]
    append_entry(path, _entry(jobs[0]))
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) - 30], encoding="utf-8")  # the kill, mid-write

    append_entry(path, _entry(jobs[1]))
    append_entry(path, _entry(jobs[2]))

    entries = load_manifest(path)  # must not raise
    assert jobs[1].filename in entries, "the line after a torn tail was swallowed"
    assert jobs[2].filename in entries


def test_a_right_sized_wrong_content_file_is_re_fetched(tmp_path: Path) -> None:
    """plan vouched for a file on LENGTH alone while the manifest entry it had just read
    carried the sha256. A right-sized wrong-content file was skipped forever and reported
    Complete -- and "the corpus is complete" is the claim this tool exists to make truthfully.
    """
    jobs = jobs_mod.STAGES["season-raw"][:3]
    done = {job.filename: _entry(job) for job in jobs}
    on_disk = {job.filename: 1234 for job in jobs}
    digests = {job.filename: "0" * 64 for job in jobs}  # matches _entry's sha256
    assert plan(jobs, done, on_disk, digests) == []

    digests[jobs[1].filename] = "f" * 64  # same size, different bytes
    assert plan(jobs, done, on_disk, digests) == [jobs[1]]


def test_plan_without_digests_still_works_but_says_less(tmp_path: Path) -> None:
    """CONTROL. The digest argument is optional only so a caller that genuinely cannot hash
    can say so; omitting it must not silently queue everything or silently skip everything."""
    jobs = jobs_mod.STAGES["season-raw"][:3]
    done = {job.filename: _entry(job) for job in jobs}
    on_disk = {job.filename: 1234 for job in jobs}
    assert plan(jobs, done, on_disk) == []
    assert plan(jobs, done, {}) == jobs


def test_switch_kind_re_reads_the_whole_scope_not_just_the_file_type() -> None:
    """The proj fetch is the one payload verify_payload cannot scope-check -- a proj export
    has no season_year or week column -- so this read-back is the only thing between a
    session that dropped mid-witness and a 2026 wk0 file written under a 2019 name."""
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()
    driver.prepare("raw", 2019, 0, "average")
    page.reset()  # the session drops between the witness and the proj fetch
    with pytest.raises(driver_mod.SessionLost, match="drifted before the fetch"):
        driver.switch_kind("proj", 2019, 0)


def test_establish_refuses_a_session_with_no_token() -> None:
    """Without a token, assert_same_session degrades to a presence check for the WHOLE RUN:
    it would only ever notice the control disappearing, never the session being replaced."""
    page = FakeShinyPage()
    page.evaluate_href_override = {"found": True, "href": "download/x?w=1", "text": "Download"}
    driver = _driver_on(page)
    with pytest.raises(driver_mod.SessionLost, match="no session id"):
        driver.establish()


def test_the_combined_read_back_includes_the_aggregation() -> None:
    """It omitted AVG_INPUT while its comment claimed "every input" -- and the aggregation
    is the one whose corruption is the defect this whole tool exists to prevent.

    THE JOB MUST TAKE NO SETTINGS TRIP. `set_input` does its own read-back, so a robust job
    reads AVG_INPUT while setting it and this gate passed whether or not `_assert_scope`
    looked at it at all -- vacuous, and the mutation sweep is what said so. A weighted job
    straight after a real year change takes no trip, so the only thing that can read
    AVG_INPUT is the combined check at the end.
    """
    page = FakeShinyPage()
    driver = _driver_on(page)
    driver.establish()

    reads: list[str] = []
    original = driver.read_input

    def read(name: str) -> str | None:
        reads.append(name)
        return original(name)

    driver.read_input = read  # type: ignore[method-assign]
    driver.prepare("raw", 2020, 0, "weighted")  # 2026 -> 2020 resets to weighted; no trip
    assert "click:tab_settings" not in page.calls, "the job took a trip; gate is vacuous"
    assert driver_mod.AVG_INPUT in reads, reads


def test_an_output_that_pauses_and_resumes_is_not_called_permanently_stuck(
    monkeypatch,
) -> None:
    """wait_idle measured cumulative appearance, not continuity, so an output that resolved
    and then legitimately started a SECOND recalculation was reclassified as one that never
    resolves -- on the strength of two short busy spells separated by an idle one. The
    docstring said "stays continuously busy"; the code did not."""
    page = FakeShinyPage()
    settles = replace(INSTANT, idle_timeout=30.0, stuck_after=4.0)
    driver = driver_mod.ShinyDriver(page, settles, log=lambda _m: None)
    driver.establish()

    clock = {"t": 1000.0}
    monkeypatch.setattr(driver_mod.time, "time", lambda: clock["t"])
    monkeypatch.setattr(
        driver_mod.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s)
    )

    # TWO outputs, alternating out of phase, so `busy` is NEVER empty -- otherwise wait_idle
    # simply returns on the first pause and the resume never happens, which is why the first
    # version of this gate was vacuous and the sweep caught it.
    #
    # Neither is ever busy for stuck_after (1.0s = 4 polls) continuously: each runs for
    # three polls (0.75s) then rests for three. Cumulatively each passes 1.0s almost at
    # once, so a driver measuring appearance rather than continuity reclassifies both.
    polls = {"n": 0}
    original = page.evaluate

    def evaluate(script: str, arg: object = None) -> object:
        if script is driver_mod._BUSY_JS:
            polls["n"] += 1
            phase = ((polls["n"] - 1) // 3) % 2
            return {"busy": ["output_a" if phase == 0 else "output_b"], "pending": 0}
        return original(script, arg)

    page.evaluate = evaluate  # type: ignore[method-assign]
    driver.settles = replace(driver.settles, idle_timeout=3.0, stuck_after=1.0)
    driver.wait_idle()
    assert "output_a" not in driver._idle_baseline, (
        "an output that paused and resumed was called permanently stuck"
    )
    assert "output_b" not in driver._idle_baseline
    assert polls["n"] > 8, f"only {polls['n']} polls; the loop did not run long enough"


def test_the_modal_probe_never_dismisses() -> None:
    """The probe and the dismiss were one script. Asking "did it close?" therefore CLOSED
    whatever was up -- a second modal was dismissed without ever being logged, and the
    driver reported on a modal it had itself actuated."""
    page = FakeShinyPage()
    page.modal = "Something"
    driver = _driver_on(page)
    state = driver.page.evaluate(driver_mod._MODAL_PROBE_JS)
    assert state["present"] and state["dismissible"]
    assert page.modal == "Something", "the probe dismissed the modal"
    assert page.dismissals == 0


def test_a_second_modal_is_named_rather_than_the_one_just_closed() -> None:
    """ModalBlocked used to carry the text of the modal that HAD been dismissed, sending a
    reader looking for the wrong message."""
    page = FakeShinyPage()
    page.modal = "First message"
    original = page.evaluate

    def evaluate(script: str, arg: object = None) -> object:
        result = original(script, arg)
        if script is driver_mod._MODAL_DISMISS_JS:
            page.modal = "Second message"  # a different one behind it
        return result

    page.evaluate = evaluate  # type: ignore[method-assign]
    driver = _driver_on(page)
    with pytest.raises(driver_mod.ModalBlocked) as caught:
        driver.clear_modal()
    assert "Second message" in str(caught.value), caught.value
    assert "First message" in str(caught.value), "the dismissed one should be named too"


def test_the_browser_profile_directory_is_ignored_by_git() -> None:
    """It is the only credential store this tool creates -- a live session cookie for a
    paid account -- and nothing asserted it was ignored. The corpus had three gates; this
    had none."""
    from .tools.ffa_scrape.__main__ import DEFAULT_PROFILE

    relative = DEFAULT_PROFILE.relative_to(_REPO).as_posix()
    proc = subprocess.run(
        ["git", "check-ignore", "-v", f"{relative}/Default/Cookies"],
        cwd=_REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"{relative} is NOT ignored by git"
    assert ".gitignore" in proc.stdout


def test_no_live_session_identifier_is_committed() -> None:
    """A real session id and worker token captured from a logged-in paid session were
    pasted into a module docstring and a fixture. Ephemeral and long dead, but there is no
    reason for a public repository to carry them."""
    # Assembled from halves so this gate does not itself carry what it forbids -- which is
    # exactly what it did on its first run, and it caught itself.
    captured = (
        "f8ef99aeb854208d" + "8b1abc8914a0276b",
        "32ee825bd77448a6" + "a38c279b8174d2a1",
    )
    tracked = subprocess.run(
        ["git", "ls-files", "sim/"], cwd=_REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    for name in tracked:
        text = (_REPO / name).read_text(encoding="utf-8", errors="ignore")
        for token in captured:
            assert token not in text, f"{name} carries a captured session identifier"


# ---------------------------------------------------------------------------------------
# A PLAYWRIGHT ERROR IS A LOST SESSION WEARING SOMEONE ELSE'S TYPE.
#
# The first guard for this was `except (SessionLost, Recoverable)`, where Recoverable was a
# class whose metaclass `__instancecheck__` matched on `__name__`. It was INERT: CPython
# matches except clauses through PyType_IsSubtype, which never consults __instancecheck__,
# so `isinstance(exc, Recoverable)` answered True while the clause let the exception
# straight through. The guard silently reverted to `except SessionLost` and the defect it
# was written to fix was still there.
#
# Nothing caught that, because every session-loss gate injects SessionLost -- which matches
# by real subtyping and exercises only the half that already worked. These raise types that
# are NOT SessionLost subclasses, which is the whole point.
# ---------------------------------------------------------------------------------------


class PlaywrightishError(Exception):
    """Stands in for playwright's `Error`, whose __name__ is exactly 'Error'."""


PlaywrightishError.__name__ = "Error"


class PlaywrightishTimeout(Exception):
    pass


PlaywrightishTimeout.__name__ = "TimeoutError"


class UnrelatedError(Exception):
    """Not a name the driver knows. Must NOT be swallowed."""


@pytest.mark.parametrize("boom", [PlaywrightishError, PlaywrightishTimeout])
def test_a_playwright_error_is_recovered_from_not_fatal(
    boom: type[Exception], tmp_path: Path
) -> None:
    """The exact failure that ended stage 2 eight files in: a modal intercepted a tab click
    and the resulting TimeoutError escaped run_jobs, killing the run with seven good files
    on disk and nothing recorded to say why."""
    job = Job(kind="raw", year=2020, week=0, avg="weighted")
    fake, result = _run(
        {job.filename: [boom, raw_csv(avg_type="weighted", season_year="2020", week_col="0")]},
        [job],
        tmp_path,
    )
    assert fake.establishes == 1, "the session was not re-established"
    assert result.recoveries == 1
    assert result.completed == [job.filename], result.failed


def test_an_unknown_exception_still_kills_the_run(tmp_path: Path) -> None:
    """CONTROL, and the reason this is a NAME list rather than `except Exception`. A guard
    that swallowed everything would turn a genuine bug into an infinite retry loop against
    someone else's server."""
    job = Job(kind="raw", year=2020, week=0, avg="weighted")
    with pytest.raises(UnrelatedError):
        _run({job.filename: [UnrelatedError, UnrelatedError]}, [job], tmp_path)


def test_a_lapsed_login_is_never_treated_as_recoverable(tmp_path: Path) -> None:
    """NotLoggedIn is the one failure a human has to fix. Retrying it 600 times against
    someone else's server is the opposite of helpful."""
    assert not runner.is_recoverable(driver_mod.NotLoggedIn("locked"))
    job = Job(kind="raw", year=2020, week=0, avg="weighted")
    with pytest.raises(driver_mod.NotLoggedIn):
        _run({job.filename: [driver_mod.NotLoggedIn]}, [job], tmp_path)


def test_the_recoverable_check_is_not_an_except_clause_trick() -> None:
    """The mechanism, pinned. `isinstance` and except-clause matching disagree for a class
    with a custom __instancecheck__, and this code must not depend on the latter."""
    assert runner.is_recoverable(PlaywrightishError("navigation"))
    assert runner.is_recoverable(driver_mod.SessionLost("gone"))
    assert not runner.is_recoverable(UnrelatedError("real bug"))
    assert not hasattr(runner, "Recoverable"), (
        "the inert metaclass class is back; except clauses do not consult __instancecheck__"
    )


# ---------------------------------------------------------------------------------------
# ORDERING IS COST. A Settings->Projections round trip is the expensive move; a week change
# is a 2s settle. Aggregation therefore sits OUTSIDE week in the loop nesting.
# ---------------------------------------------------------------------------------------


def _settings_trips(jobs: list[Job]) -> int:
    """How many jobs must pay a Settings round trip, given the driver's own rule.

    A real year change resets the aggregation to weighted server-side, so a weighted job
    following one is free. Everything else that changes aggregation pays.
    """
    trips = 0
    previous: Job | None = None
    for job in jobs:
        if previous is not None and (job.avg != previous.avg or job.year != previous.year):
            free = job.year != previous.year and job.avg == "weighted"
            if not free:
                trips += 1
        previous = job
    return trips


def test_the_alternating_stage_pays_two_settings_trips_a_season_not_thirty_four() -> None:
    """With week outside aggregation, `weekly-alt` alternates average/robust on EVERY job
    and pays 374 round trips -- about an extra hour and a half against someone else's
    server for no data at all."""
    trips = _settings_trips(jobs_mod.STAGES["weekly-alt"])
    seasons = len(jobs_mod.WEEKLY_YEARS)
    assert trips <= 2 * seasons + 1, f"{trips} trips for {seasons} seasons"
    assert trips < 100, f"{trips} trips -- aggregation is being switched per week"


def test_aggregation_runs_outside_week() -> None:
    """The mechanism, so the nesting cannot be swapped back without a red gate."""
    alt = jobs_mod.STAGES["weekly-alt"]
    first_season = [job for job in alt if job.year == jobs_mod.WEEKLY_YEARS[0]]
    weeks_of_first_avg = [job.week for job in first_season if job.avg == first_season[0].avg]
    assert weeks_of_first_avg == list(jobs_mod.REGULAR_WEEKS), (
        "an aggregation does not run all its weeks consecutively"
    )


def test_the_reordering_changed_no_other_stage() -> None:
    """Every other stage holds a single week or a single aggregation, so the nesting cannot
    reorder it. If one of these ever changes, a resume against an existing manifest would
    still be correct -- order does not affect `plan` -- but the cost model would have moved
    without anyone saying so."""
    assert [job.avg for job in jobs_mod.STAGES["season-raw"][:3]] == [
        "weighted", "average", "robust"
    ]
    assert [job.week for job in jobs_mod.STAGES["weekly-weighted"][:3]] == [1, 2, 3]
    assert len(jobs_mod.STAGES["weekly-weighted"]) == 187
    assert len(jobs_mod.STAGES["season-raw"]) == 27
    assert len(jobs_mod.STAGES["season-proj"]) == 27
    assert len(jobs_mod.STAGES["weekly-alt"]) == 374


# ---------------------------------------------------------------------------------------
# THE RAW SCHEMA IS THREE SHAPES, NOT ONE, and both omissions are scoring-relevant. Found by
# an adversarial reviewer's own audit, not by this session's -- mine checked that rows are
# not ragged WITHIN a file and never compared column sets ACROSS files.
# ---------------------------------------------------------------------------------------

_REC_COLUMNS = frozenset({"rec", "rec_sd"})
_IDP_COLUMNS = frozenset({
    "idp_solo", "idp_solo_sd", "idp_sack", "idp_sack_sd", "idp_int", "idp_int_sd",
    "idp_pd", "idp_pd_sd", "idp_td", "idp_td_sd",
})


@pytest.mark.skipif(not _corpus_present(), reason="gitignored corpus not on this machine")
def test_the_raw_schema_has_exactly_three_known_shapes() -> None:
    """A fourth shape is a schema change, and a schema change is a reason to look rather
    than to carry on joining files that no longer line up."""
    widths: dict[int, int] = {}
    for path in sorted(_CORPUS.glob("ffa_raw_*.csv")):
        columns = inspect_csv(path.read_text(encoding="utf-8")).columns
        widths[len(columns)] = widths.get(len(columns), 0) + 1
    assert set(widths) == {55, 63, 65}, widths
    assert widths[65] > widths[63] + widths[55], "the full schema should be the common case"


@pytest.mark.skipif(not _corpus_present(), reason="gitignored corpus not on this machine")
def test_rec_is_present_in_every_weekly_file_and_no_alt_season_file() -> None:
    """The one that decides whether a PPR league can be scored.

    Both of Eric's leagues pay per reception. `sim/ffa.py` already carries the rule this
    earns: a missing scoring key must RAISE, never default to zero, because a PPR board
    scored with silent zeros looks entirely plausible and is not.
    """
    weekly_without: list[str] = []
    season_with: list[str] = []
    for path in sorted(_CORPUS.glob("ffa_raw_*.csv")):
        _kind, _year, week, avg = parse_filename(path.name)
        columns = set(inspect_csv(path.read_text(encoding="utf-8")).columns)
        has_rec = columns >= _REC_COLUMNS
        if week > 0 and not has_rec:
            weekly_without.append(path.name)
        if week == 0 and has_rec and avg != "weighted":
            season_with.append(path.name)
    assert weekly_without == [], f"weekly files without rec: {weekly_without}"
    # If FFA ever starts shipping rec in the alternate season aggregations, that is good
    # news and the README stops being true -- so it must fail here rather than quietly.
    assert season_with == [], f"alt-aggregation season files now carry rec: {season_with}"


@pytest.mark.skipif(not _corpus_present(), reason="gitignored corpus not on this machine")
def test_an_absent_idp_column_set_is_distinguished_from_an_empty_one() -> None:
    """Reading idp_solo from a file that lacks the column raises; from a file that has the
    column and no defenders it returns nothing. A loader that treats those alike, or that
    treats either as zero, is the silent-zeros failure on the IDP axis."""
    absent = present_but_empty = 0
    for path in sorted(_CORPUS.glob("ffa_raw_*.csv")):
        report = inspect_csv(path.read_text(encoding="utf-8"))
        has_columns = set(report.columns) >= _IDP_COLUMNS
        has_rows = bool(set(report.positions) & NINE_POSITIONS & {"DL", "LB", "DB"})
        if not has_columns:
            absent += 1
            assert not has_rows, f"{path.name} has IDP rows without IDP columns"
        elif not has_rows:
            present_but_empty += 1
    assert absent > 0 and present_but_empty > 0, (
        f"both shapes must occur for this distinction to be real: "
        f"absent={absent} present_but_empty={present_but_empty}"
    )
    assert absent + present_but_empty == 93, absent + present_but_empty
