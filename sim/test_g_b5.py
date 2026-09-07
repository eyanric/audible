"""GATES G1-G17 for B5, plus the eight failure injections.

B5 ASKS B4'S QUESTION ON THE INPUT B4 DID NOT HAVE. Does audible's replacement transform earn
its place, or is it a coat of paint over ADP? B4 could only ask it against a projection the
harness built for itself, which was mediocre; `sim/data/ffa/` now holds the market's own
vintage preseason numbers, so the same comparison runs on a market-grade input.

THE GATE ON THE WHOLE SESSION IS STILL G2. B3's defect was a board that was a monotone
transform of ADP rank, 128 of 128 exact in every season, which made two sessions of arm
comparisons measurements of the ordering overlay on the market's own list. `test_g2_*` asserts
these boards are not that and `test_i1_*` reproduces the defect on purpose.

WHAT THIS FILE ASSERTS THAT NO EARLIER ONE COULD. G1 is a JOIN gate with a number, not a
hope: the FFA export is keyed on MFL ids and every board row has to reach one. G3 is the
scoring-gap gate, and it reads the EFFECTIVE weights rather than a hardcoded list of seasons,
which is what makes it right for both a league that pays for receptions and one that does not.
G5 re-derives each season's following-year draft class FROM THE NEXT SEASON'S OWN FILE instead
of trusting five names in a README.

THREE README CLAIMS ARE REFUTED HERE, and each refutation is a test rather than a remark:

  * `test_g3_the_reception_column_is_absent_from_seven_of_nine_seasons` -- the README says the
    bare `rec` column is missing from 2021 and 2023 and present in five other seasons. Of the
    nine season files on disk it exists in 2024 and 2025 ONLY.
  * `test_g10_defences_are_held_at_zero_on_both_sides` -- the README says kickers and defences
    "score for the first time". FFA projects both, but the OUTCOME comes from nflverse, which
    carries kicking columns and NO team-defence rows at all, so a defence cannot be scored and
    is held at zero on both sides rather than projected on one and paid on neither.
  * `test_g_the_2019_and_2020_seasons_are_blocked_by_the_market_not_the_outcome` -- a prior
    session recorded
    `player_stats_2020` as absent. It fetches cleanly. What blocks those seasons is the MARKET
    side, and the gate says so.

WHAT THESE GATES CANNOT SAY, stated so nobody reads them as broader than they are. They say
nothing about whether AUDIBLE'S OWN projections beat the market: the projections here are
FFA's, production consumes a different consensus source, and no vintage of that exists. And
they measure ORDERING only -- bots fitted to ADP are not people and do not stack, reach for
their own players, or panic.

WHEN THE CSVs ARE ABSENT most of this file skips, because the data is subscription-derived and
gitignored and cannot be committed. That is a real weakness and not a footnote: on a fresh
checkout the honest state of these gates is "not run". `test_g17_*` and the config gates still
execute, and they are the ones that hold when the data is not there.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "sim" / "runs"
CONFIG = REPO / "sim" / "configs" / "b5-vintage.toml"
ARTIFACT = RUNS / "b5-vintage.json"
FFA_DIR = REPO / "sim" / "data" / "ffa"

# The seasons the ROOM can replay. Tighter than the projections, and the reason is the market
# side: a run season needs a pinned FFC board and a pinned completed 6012 draft as well as an
# outcome frame, and those exist for 2021-2025 only.
SEASONS = (2021, 2022, 2023, 2024, 2025)

pytestmark = pytest.mark.slow


def _require(name: str) -> Path:
    for root in (SIM_CACHE, LIVE_CACHE):
        if (root / name).exists():
            return root / name
    pytest.skip(f"{name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}")


def _require_csv(season: int) -> Path:
    path = FFA_DIR / f"raw_stats_{season}_wk0.csv"
    if not path.exists():
        pytest.skip(
            f"{path.name} is not on disk. The FFA CSVs are gitignored and "
            f"subscription-derived; see sim/data/ffa/README.md."
        )
    return path


@pytest.fixture(scope="module")
def mods():
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    from . import artifact, boards, ffa, room, roundtrip, runner, seat, weekly

    _require("nflverse/ff_playerids.parquet")
    for season in SEASONS:
        _require(f"nflverse/player_stats_{season}.parquet")
        _require(f"ffc_adp_standard_8_{season}.json")
    return artifact, boards, ffa, room, roundtrip, runner, seat, weekly


@pytest.fixture(scope="module")
def league(mods):
    _artifact, _boards, ffa, _room, roundtrip, *_rest = mods
    from audible.config import load_league

    config = load_league(REPO / "leagues" / "espn_davis_drive.toml")
    return ffa.with_deltas(config, roundtrip.HISTORICAL_DELTAS)


@pytest.fixture(scope="module")
def built(mods, league):
    """Every season's boards, built once. Expensive, and every board gate reads it."""
    _artifact, boards, ffa, *_rest = mods
    for season in SEASONS:
        _require_csv(season)
    return {
        season: boards.build(season, league, source=boards.FFA_SOURCE, deltas=None)
        for season in SEASONS
    }


@pytest.fixture(scope="module")
def committed(mods):
    artifact, *_rest = mods
    if not ARTIFACT.exists():
        pytest.skip(f"{ARTIFACT} is not committed yet")
    return artifact.read(ARTIFACT)


# --- G1: the join is proven, with a number -----------------------------------------------------


def test_g1_the_mfl_crosswalk_reaches_almost_every_projected_player(mods) -> None:
    """The FFA export is keyed on MFL ids and `ff_playerids` carries `mfl_id` beside `gsis_id`.

    THIS IS THE HIGHEST-RISK STEP IN THE SESSION and it is asserted rather than assumed.
    `weekly.prior_points` once looked players up with `ffc####` keys against a roster keyed on
    gsis ids; every lookup missed, every prior read 0.0, and because `optimal_week` is an exact
    matching every lineup tied and fell out of the tie-break. Two sessions of headline numbers
    were computed against arbitrary lineups before anyone noticed. A silent join failure here
    produces a board built entirely from defaults that looks completely reasonable.

    THE FLOOR EXCLUDES TEAM DEFENCES DELIBERATELY. A D/ST is not a person and has no gsis id;
    it joins on team abbreviation. Measured, every season is 99.4-100.0% on everyone else.
    """
    pytest.importorskip("nflreadpy")
    import csv

    import nflreadpy as nfl

    ids = nfl.load_ff_playerids()
    assert "mfl_id" in ids.columns, "ff_playerids no longer carries mfl_id"
    assert "gsis_id" in ids.columns, "ff_playerids no longer carries gsis_id"
    crosswalk = {
        str(row["mfl_id"]).strip(): row["gsis_id"]
        for row in ids.select(["mfl_id", "gsis_id"]).iter_rows(named=True)
        if row["mfl_id"] is not None
    }

    for season in SEASONS:
        path = _require_csv(season)
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        seen: set[str] = set()
        people = []
        for row in rows:
            ident = (row.get("id") or "").strip()
            if not ident or ident in seen:
                continue
            seen.add(ident)
            if row.get("position") != "DST":
                people.append(ident)
        matched = sum(1 for ident in people if crosswalk.get(ident))
        rate = matched / len(people)
        assert rate >= 0.99, (
            f"G1 join: season {season} matched {matched} of {len(people)} non-defence players "
            f"({rate:.1%}) through mfl_id -> gsis_id. Below this the board is built from "
            f"defaults and looks entirely reasonable."
        )


def test_g1_the_join_production_uses_is_the_one_measured(mods, league) -> None:
    """THE REAL JOIN IS `board_key`, not the id crosswalk, and this is what measures it.

    The crosswalk gate above is worth having -- it proves the MFL ids resolve, which is what
    the handoff asked for -- but `ffa.build` does not join on it. It joins a `room.BoardRow` to
    an FFA row through `ffa.board_key`: a normalised name, or `DEF:<team>` for a defence. A
    gate that only measured the crosswalk would sit green through a total failure of the join
    that actually runs.
    """
    _artifact, _boards, ffa, room, *_rest = mods
    for season in SEASONS:
        _require_csv(season)
        board = room.load_board(season)
        keys = {
            ffa.board_key(
                row.get("player") or "",
                ffa.POSITION_MAP.get(row.get("position") or "", row.get("position") or ""),
                row.get("team"),
            )
            for row in ffa.read_raw(season)
        }
        hit = sum(1 for row in board.rows[:128] if row.key in keys)
        assert hit >= 120, (
            f"G1 board join: season {season} matched {hit} of the drafted top 128 through "
            f"`board_key`. Below this the board is mostly empty stat lines that sort last."
        )


def test_i2_a_broken_join_key_collapses_g1(mods, monkeypatch) -> None:
    """INJECTION 2. Break the join key; G1's board-side rate must collapse.

    The historic failure this stands for: `weekly.prior_points` keyed `ffc####` against a
    gsis-keyed roster, every lookup missed, every prior read 0.0, and two sessions of headline
    numbers were computed against lineups chosen by tie-break. A join can fail totally and
    leave a board that looks entirely reasonable, so the gate needs to be shown failing.
    """
    _artifact, _boards, ffa, room, *_rest = mods
    _require_csv(2024)
    board = room.load_board(2024)
    monkeypatch.setattr(ffa, "board_key", lambda name, position, team: f"BROKEN:{name}")
    keys = {
        ffa.board_key(
            row.get("player") or "",
            row.get("position") or "",
            row.get("team"),
        )
        for row in ffa.read_raw(2024)
    }
    hit = sum(1 for row in board.rows[:128] if row.key in keys)
    assert hit == 0, f"a broken join key still matched {hit} of 128; the gate cannot detect it"


def test_i2_a_broken_crosswalk_collapses_the_id_join(mods) -> None:
    """INJECTION 2, the id half. Corrupt the mfl ids and the crosswalk rate must go to zero."""
    pytest.importorskip("nflreadpy")
    import nflreadpy as nfl

    ids = nfl.load_ff_playerids()
    crosswalk = {
        str(row["mfl_id"]).strip(): row["gsis_id"]
        for row in ids.select(["mfl_id", "gsis_id"]).iter_rows(named=True)
        if row["mfl_id"] is not None
    }
    _artifact, _boards, ffa, *_rest = mods
    _require_csv(2024)
    people = [
        (row.get("id") or "").strip()
        for row in ffa.read_raw(2024)
        if row.get("position") != "DST"
    ]
    intact = sum(1 for ident in people if crosswalk.get(ident))
    broken = sum(1 for ident in people if crosswalk.get(f"X{ident}"))
    assert intact / len(people) >= 0.99
    assert broken == 0, f"a corrupted id still resolved {broken} times"


def test_g1_the_board_rows_reach_a_projection(built) -> None:
    """Every arm drafts off the room's board, so what matters is coverage OF THAT BOARD.

    The crosswalk rate above is necessary and not sufficient: a perfect id join that reaches
    nobody the room can draft would still leave every arm ordering an empty board.
    """
    for season, boards in built.items():
        total = boards.matched + boards.unmatched
        assert boards.matched / total >= 0.97, (
            f"G1 coverage: season {season} projected only {boards.matched} of {total} board "
            f"rows. The rest carry an empty stat line and sort last."
        )


# --- G2: the board is not ADP ------------------------------------------------------------------


def g2_failures(row: dict) -> list[str]:
    """G2 as a PREDICATE, so the gate and its injection run the same code.

    A gate whose injection re-implements the check is two checks that can drift apart, and the
    injection then proves the copy fires rather than the gate.
    """
    out: list[str] = []
    if row["exact_of_128"] >= 32:
        out.append(
            f"G2 board-is-adp: the board matches ADP exactly on {row['exact_of_128']} of the "
            f"top 128. That is the B3 defect -- the board IS the market."
        )
    if row["disagree_over_one_round"] <= 32:
        out.append(
            f"G2 board-is-adp: only {row['disagree_over_one_round']} of the top 128 move by "
            f"more than a round; the comparison is not exercising the board."
        )
    if row["pearson"] >= 0.99:
        out.append(f"G2 board-is-adp: pearson {row['pearson']} against ADP rank")
    return out


def test_g2_the_board_disagrees_with_adp(built) -> None:
    """THE GATE ON THE WHOLE SESSION. B3's defect was 128/128 exact; this must not be that.

    IT READS THE ORDER THE ARM ACTUALLY DRAFTS. `vs_adp` is computed from `orders`, the room
    index tuples the chooser is handed, and not from a rank field sitting on an entry. That
    distinction is what let the B3 defect pass clean once already: a gate that reads a
    hardcoded rank cannot see that the ordering derived from it is the market's own.
    """
    for season, boards in built.items():
        row = boards.vs_adp["audible_transform"]
        assert not g2_failures(row), f"season {season}: {g2_failures(row)}"


def test_i1_an_adp_ordered_board_fails_g2(built, mods) -> None:
    """INJECTION 1. Point the transform at the ADP-ordered board; G2 must fire, 128/128 exact.

    This is the injection that guards the whole session, because it reproduces the exact defect
    that made two prior sessions meaningless.
    """
    for season, boards in built.items():
        row = boards.vs_adp["adp_board"]
        assert row["exact_of_128"] == 128, (
            f"season {season}: the ADP-ordered board should match ADP on all 128, got "
            f"{row['exact_of_128']}"
        )
        assert g2_failures(row), "G2 did not fire on an ADP-ordered board"


# --- G3: a missing scoring key raises, never defaults ------------------------------------------


def test_g3_the_reception_column_is_absent_from_seven_of_nine_seasons(mods) -> None:
    """REFUTES THE README. It says `rec` is missing from 2021 and 2023 only; it is in two.

    The README's derived claim -- "PPR scoring 2019, 2020, 2022, 2024, 2025" -- is wrong in
    both directions, and a run that trusted it would score three seasons of a PPR league with
    silent zeros.
    """
    _artifact, _boards, ffa, *_rest = mods
    present: list[int] = []
    seen: list[int] = []
    for season in range(2018, 2027):
        if not (FFA_DIR / f"raw_stats_{season}_wk0.csv").exists():
            continue
        seen.append(season)
        if "rec" in ffa.columns(season):
            present.append(season)
    if not seen:
        pytest.skip("no FFA CSVs on disk")
    assert present == [2024, 2025], (
        f"the bare `rec` column is present in {present} of the {len(seen)} seasons on disk, "
        f"not the README's [2019, 2020, 2022, 2024, 2025]"
    )


def test_g3_a_missing_scoring_key_raises_under_a_ppr_league(mods) -> None:
    """INJECTION 3, and the gate. A PPR league over a season with no `rec` column must RAISE.

    `score_stat_line` resolves an absent key with `stats.get(key, 0.0)`, so without this the
    board is scored under standard rules, looks entirely plausible, and is wrong.
    """
    _artifact, _boards, ffa, *_rest = mods
    from audible.config import load_league

    _require_csv(2021)
    ppr = load_league(REPO / "leagues" / "espn_danger_zone.toml")
    assert ppr.scoring_for("WR")["rec"] == 1.0, "espn_danger_zone no longer pays for receptions"
    with pytest.raises(ffa.ScoringGapError, match="rec"):
        ffa.assert_scoreable(2021, ppr)


def test_g3_the_same_season_is_fine_for_a_league_that_pays_nothing_per_reception(
    mods, league
) -> None:
    """The other half of G3, and the reason it reads EFFECTIVE weights and not a season list.

    League 6012 paid 0.0 a reception in 2021-2025, so an absent reception count changes no
    score. A hardcoded "PPR seasons" list cannot express that a gap is fatal for one league and
    irrelevant for another over the very same file.
    """
    _artifact, _boards, ffa, *_rest = mods
    _require_csv(2021)
    assert league.scoring_for("WR")["rec"] == 0.0
    ffa.assert_scoreable(2021, league)


def test_g3_every_unsupplied_term_is_declared_and_recorded(built) -> None:
    """A gap is either DECLARED or FATAL, and never silent. The declared ones reach the artifact."""
    for season, boards in built.items():
        assert boards.unsupplied, f"season {season} declared no unsupplied terms at all"
        assert "sack" in boards.unsupplied, "team D/ST terms must be declared, not mapped"


# --- G4: arms 1, 2 and 4 share one board -------------------------------------------------------


def test_g4_the_three_projected_arms_share_one_projection(built) -> None:
    """`points_greedy`, `audible_transform` and `ffa_vor` must read ONE set of stat lines.

    Building both arms from a single board is a stronger form of this than comparing two
    digests would be, but the digest is recorded PER ARM so a gate can fail if someone ever
    builds them separately. That is the failure this exists for.
    """
    for season, boards in built.items():
        # The STAT-LINE half of the digest is the shared claim. The FFA arms append a value
        # digest after a slash, because the stat-line digest alone cannot see a change to the
        # external column they order on -- a review negated every `points_vor` and watched the
        # shared digest sit still. Split on the slash and compare the half that must match.
        shared = {
            arm: boards.arm_digest[arm].split("/")[0]
            for arm in ("points_greedy", "audible_transform", "ffa_baseline", "ffa_vor")
            if arm in boards.arm_digest
        }
        assert len(shared) >= 3, f"season {season}: expected the FFA arms, got {sorted(shared)}"
        assert len(set(shared.values())) == 1, (
            f"season {season}: arms do not share one projection: {shared}"
        )
        # ...and the value digest MUST differ between the two FFA arms, or they are the same
        # ordering wearing two names.
        if "ffa_baseline" in boards.arm_digest and "ffa_vor" in boards.arm_digest:
            assert boards.orders["ffa_baseline"] != boards.orders["ffa_vor"], (
                f"season {season}: ffa_baseline and ffa_vor produced the same ordering"
            )


def test_i5_two_different_boards_fail_g4(mods, league) -> None:
    """INJECTION 5. Build arms 1 and 2 off different projections; the digests must diverge."""
    _artifact, boards, _ffa, *_rest = mods
    _require_csv(2024)
    ffa_board = boards.build(2024, league, source=boards.FFA_SOURCE)
    walk = boards.build(2024, league, source=boards.WALKFORWARD)
    assert ffa_board.projected_digest != walk.projected_digest, (
        "two different projection sources produced the same digest; G4 could not distinguish "
        "them and the comparison would be between two different universes"
    )


def test_i6_an_identity_transform_collapses_the_difference(mods, league, monkeypatch) -> None:
    """INJECTION 6. MUTATE the transform to the identity; the two orderings must become equal.

    Observing that two orderings differ is not this injection -- it is just the gate restated.
    The mutation is a replacement level of ZERO at every position, which is exactly what the
    transform being the identity means: `vorp = points - 0` orders identically to `points`.
    Under it `transform - points` collapses to 0.0, and the fact that it does NOT collapse on
    the real boards is what says the headline is measuring something.
    """
    _artifact, boards, _ffa, *_rest = mods
    from audible.value import replacement as repl

    _require_csv(2024)
    real = boards.build(2024, league, source=boards.FFA_SOURCE)
    assert real.orders["points_greedy"] != real.orders["audible_transform"]

    original = repl.replacement_levels

    def flat(players, config, starters=None):
        levels = original(players, config, starters)
        return {
            pos: type(level)(
                position=level.position, points=0.0, starters_used=level.starters_used,
                rostered=level.rostered, replacement_rank=level.replacement_rank,
            )
            for pos, level in levels.items()
        }

    monkeypatch.setattr(repl, "replacement_levels", flat)
    mutant = boards.build(2024, league, source=boards.FFA_SOURCE)
    assert mutant.orders["points_greedy"] == mutant.orders["audible_transform"], (
        "with every replacement level forced to 0.0 the VORP ordering must equal the raw "
        "points ordering; it does not, so something other than replacement level is moving "
        "the board and `transform - points` is not the transform"
    )


# --- G5: vintage -------------------------------------------------------------------------------


def test_g5_no_season_carries_the_following_years_draft_class(mods) -> None:
    """The check the README did by hand, done from the data and over the whole class.

    For season S the class is every player in the S+1 file whose `draft_year` is S+1 -- 54 to
    178 names -- rather than five typed from memory.
    """
    _artifact, _boards, ffa, *_rest = mods
    checked = 0
    for season in range(2018, 2026):
        if not (FFA_DIR / f"raw_stats_{season}_wk0.csv").exists():
            continue
        if not (FFA_DIR / f"raw_stats_{season + 1}_wk0.csv").exists():
            continue
        expected = ffa.following_class(season)
        assert len(expected) >= 40, (
            f"season {season + 1} draft class came back as {len(expected)} names; the check "
            f"is not exercising anything"
        )
        ffa.assert_vintage(season)
        checked += 1
    if not checked:
        pytest.skip("no consecutive FFA CSV pair on disk")


def test_i7_a_following_year_rookie_fires_g5(mods, tmp_path, monkeypatch) -> None:
    """INJECTION 7. Inject a 2025 rookie into the 2024 file; G5 must fire."""
    _artifact, _boards, ffa, *_rest = mods
    import csv
    import shutil

    _require_csv(2024)
    _require_csv(2025)
    staged = tmp_path / "ffa"
    staged.mkdir()
    for season in (2024, 2025):
        for template in (ffa.RAW_FILE, ffa.PROJ_FILE):
            shutil.copy(FFA_DIR / template.format(season=season), staged)

    victim = staged / ffa.RAW_FILE.format(season=2024)
    with victim.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    leak = dict(rows[0])
    leak["player"] = "Ashton Jeanty"
    # POSITION TOO. `assert_vintage` matches on (name, position) so that linebacker Josh Allen
    # cannot be mistaken for quarterback Josh Allen; an injection that copies a quarterback row
    # and renames it therefore does NOT fire, and the first version of this test did not.
    leak["position"] = "RB"
    leak["id"] = "999999"
    rows.append(leak)
    with victim.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr(ffa, "FFA_DIR", staged)
    with pytest.raises(ffa.VintageError, match="draft class"):
        ffa.assert_vintage(2024)


# --- G6: the pool margin -----------------------------------------------------------------------


def test_g6_every_position_has_a_real_replacement_pool(mods, league) -> None:
    """Replacement level is the best projected player nobody rosters. A short pool reads 0.0.

    `replacement_levels` resolves an exhausted pool with
    `at_pos[taken].points if taken < len(at_pos) else 0.0`, which hands every player at that
    position his FULL projection as VORP and inflates precisely the arm whose entire mechanism
    is replacement level. A prior review found exactly this with 18 tight ends against 18
    rostered, which put Brock Bowers first overall.
    """
    _artifact, _boards, ffa, *_rest = mods
    for season in SEASONS:
        _require_csv(season)
        margins = ffa.assert_pool(season, league)
        for position, row in margins.items():
            if position in ffa.ZERO_POSITIONS:
                continue
            assert row["margin"] >= 8, (
                f"season {season} {position}: {row['pool']} projected against "
                f"{row['rostered']} rostered, margin {row['margin']}"
            )


def test_i4_a_truncated_pool_fails_g6(mods, league, monkeypatch) -> None:
    """INJECTION 4. Truncate a season's pool below the drafted count; G6 must fire."""
    _artifact, _boards, ffa, *_rest = mods
    _require_csv(2024)
    real = ffa.build

    def truncated(season, config, **kwargs):
        full = real(season, config, **kwargs)
        keep = [
            line
            for line in full.lines
            if line.primary_position != "TE" or line.player_id.startswith(ffa.DRAFTABLE_PREFIX)
        ]
        # Keep only a handful of tight ends -- fewer than the league rosters.
        tes = [line for line in keep if line.primary_position == "TE"][:3]
        others = [line for line in keep if line.primary_position != "TE"]
        import dataclasses

        return dataclasses.replace(
            full, lines=tuple(others + tes), pool=len(others) + len(tes)
        )

    monkeypatch.setattr(ffa, "build", truncated)
    with pytest.raises(ffa.PoolError, match="TE"):
        ffa.assert_pool(2024, league)


# --- G7: 2026 is excluded ----------------------------------------------------------------------


def test_g7_the_unplayed_season_cannot_be_an_arm(mods) -> None:
    """2026 has not happened. Loading it into an arm scores it against nothing."""
    _artifact, _boards, ffa, *_rest = mods
    assert 2026 in ffa.UNPLAYED
    assert 2026 not in ffa.SCOREABLE
    with pytest.raises(ValueError, match="has not been played"):
        ffa.assert_scoreable_season(2026)


def test_i8_a_config_naming_2026_is_refused(mods, tmp_path) -> None:
    """INJECTION 8. Add 2026 to a config's season list; preflight must refuse it."""
    _artifact, _boards, _ffa, _room, _roundtrip, runner, *_rest = mods
    text = CONFIG.read_text(encoding="utf-8").replace(
        "seasons = [2021, 2022, 2023, 2024, 2025]",
        "seasons = [2021, 2022, 2023, 2024, 2025, 2026]",
        1,
    )
    path = tmp_path / "b5-2026.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit, match="2026"):
        runner.load_config(path)


# --- G8/G9: the headline comparisons and the ceiling -------------------------------------------


HEADLINES = ("transform_minus_points", "transform_minus_adp", "transform_minus_ffa_vor")
POLICIES = ("prior", "oracle", "hindsight")


def test_g8_all_three_headlines_are_reported_under_all_three_policies(committed) -> None:
    """A headline quoted under one lineup policy is a headline chosen after the fact."""
    payload = committed
    for name in HEADLINES:
        assert name in payload, f"{name} missing from the artifact"
        for policy in POLICIES:
            key = name if policy == "prior" else f"{name}_{policy}"
            assert key in payload, f"{key} missing: {name} is not reported under {policy}"


def test_g9_every_arm_is_reported_as_a_fraction_of_the_ceiling(committed) -> None:
    """The same null means opposite things at a +40 ceiling and a +400 one."""
    payload = committed
    assert "ceiling" in payload, "no ceiling block; no arm can be read against scale"
    ceiling = payload["ceiling_minus_adp"]["mean"]
    assert isinstance(ceiling, int | float), f"ceiling is {ceiling!r}, not a number"
    assert ceiling > 50.0, (
        f"the ceiling reads {ceiling:+.1f}. Below this a null result means 'there was nothing "
        f"to find' rather than 'the arm found none of it', and every fraction below is noise."
    )
    for name in ("transform_minus_adp", "points_minus_adp", "ffa_baseline_minus_adp"):
        block = payload.get(name)
        assert block is not None, f"{name} missing; it cannot be read against the ceiling"
        assert isinstance(block["mean"], int | float)


# --- G10: the per-position decomposition -------------------------------------------------------


def test_g10_defences_are_held_at_zero_on_both_sides(mods) -> None:
    """REFUTES THE README. Kickers score for the first time; defences still cannot.

    FFA projects both. The OUTCOME comes from nflverse `player_stats`, which carries kicking
    columns (`fg_made_0_19` ... `pat_made`) and NO team-defence rows at all. A board that
    ranked defences it will never be paid for would spend real picks on them, so DEF is held at
    zero on the projection side to match the side that cannot pay.
    """
    pytest.importorskip("polars")
    import polars as pl

    _artifact, _boards, ffa, *_rest = mods
    assert "DEF" in ffa.ZERO_POSITIONS
    path = _require("nflverse/player_stats_2024.parquet")
    frame = pl.read_parquet(path)
    positions = {str(p).upper() for p in frame["position"].unique().to_list() if p}
    assert not (positions & {"DST", "DEF", "D/ST"}), (
        f"nflverse now carries team-defence rows {positions & {'DST', 'DEF', 'D/ST'}}; "
        f"defences could be scored and ZERO_POSITIONS should be revisited"
    )
    assert "K" in positions, "nflverse no longer carries kickers"
    assert "fg_made_0_19" in frame.columns and "pat_made" in frame.columns


def test_g10_the_position_and_slot_views_agree(committed) -> None:
    """A decomposition that does not sum to its own total is two different measurements.

    A prior session double-counted RB at 51% against a true 40%.
    """
    payload = committed
    by_position = payload.get("by_position")
    by_slot = payload.get("by_slot")
    if not by_position or not by_slot:
        pytest.skip("no decomposition block in this artifact")
    for label, positions in by_position.items():
        # THE TWO VIEWS, against EACH OTHER. Comparing `by_position` to `by_position_total`
        # compares a sum to its own sum and cannot fail; the defect it is meant to catch --
        # a prior session double-counting RB at 51% against a true 40% -- lives in the
        # difference between the position view and the slot view, so that is what is read.
        slots = by_slot[label]
        pos_total = sum(float(v) for v in positions.values())
        slot_total = sum(float(v) for v in slots.values())
        assert abs(pos_total - slot_total) < 0.5, (
            f"{label}: per-position sums to {pos_total:.2f} but per-slot sums to "
            f"{slot_total:.2f}; the two views disagree and one of them is double-counting"
        )
        assert abs(pos_total - float(payload["by_position_total"][label])) < 0.5
        assert abs(slot_total - float(payload["by_slot_total"][label])) < 0.5
    # K and DEF separately, because two of nine starting slots read exactly 0.0 in every run
    # before this one and the point of scoring kickers is that one of them no longer does.
    headline = by_position.get("transform_minus_points") or {}
    assert "K" in headline and "DEF" in headline, (
        f"K and DEF must be reported separately; got {sorted(headline)}"
    )


# --- G11: the controls -------------------------------------------------------------------------


def test_g11_the_null_control_and_the_leak_detector_are_present(committed) -> None:
    """`bot` at chance, `shuffle` reported, and the size ceiling live on every run."""
    payload = committed
    for arm in ("bot", "shuffle", "adp"):
        assert arm in payload["arms"], f"{arm} is required on every run and is missing"


def test_g11_the_size_ceilings_still_fire(mods) -> None:
    """G6d is a CEILING and it must not have been widened to accommodate a result.

    The signature a real leak produces is SIZE, not collapse: an oracle leak widened
    `real - shuffle` from +92 to +428 with every gate green.
    """
    _artifact, _boards, _ffa, _room, _roundtrip, runner, seat, *_rest = mods
    assert seat.LEAK_CEILING == 150.0, "the G6d ceiling was moved"
    assert runner.leak_ceiling_failures({"real_minus_adp": {"mean": 999.0}})
    assert not runner.leak_ceiling_failures({"real_minus_adp": {"mean": 10.0}})


# --- G12/G13: intervals, determinism -----------------------------------------------------------


def test_g12_intervals_are_clustered_on_season(committed) -> None:
    """Five ADP vintages and five real rooms remain five however many seeds are drawn."""
    payload = committed
    block = payload["transform_minus_points"]
    assert block.get("clusters") == 5, (
        f"expected five season clusters, got {block.get('clusters')!r}. Five ADP vintages and "
        f"five real rooms remain five however many seeds are drawn."
    )
    # FLAT WRITTEN TOO, so the ratio is computable and nobody has to take the clustering on
    # faith. The ratio is not a constant -- measured 1.25x to 3.57x on B3 -- so it is reported
    # rather than asserted at a value.
    assert block["flat_lo"] is not None and block["flat_hi"] is not None
    assert (block["hi"] - block["lo"]) >= (block["flat_hi"] - block["flat_lo"]), (
        "the clustered interval is NARROWER than the flat one; clustering on season should "
        "widen it, so the cluster argument is probably not reaching mean_and_interval"
    )


def test_g13_the_artifact_digest_is_reproducible(committed, mods) -> None:
    """The digest is over the RESULTS, so a rerun that changed a number changes the digest."""
    artifact, *_rest = mods
    # `write` sets `content_digest` AFTER computing it, so the stored value is a digest of the
    # payload WITHOUT that key. Reproducing it means removing it first; comparing against the
    # payload as read would fail on every artifact ever written.
    body = {k: v for k, v in committed.items() if k != "content_digest"}
    assert committed["content_digest"] == artifact.content_digest(body)


# --- G14: the live cache is untouched ----------------------------------------------------------


def test_g14_sim_never_writes_the_live_cockpit_cache() -> None:
    """The rebind in `sim/__init__.py` is the only mechanism that reaches the write."""
    from audible.adapters import cache as cache_mod

    assert cache_mod.DEFAULT_CACHE_DIR == SIM_CACHE
    assert SIM_CACHE.resolve() != LIVE_CACHE.resolve()


def test_g14_the_live_cache_still_holds_its_63_files() -> None:
    """A count, because a run that deleted one would otherwise be invisible here."""
    if not LIVE_CACHE.exists():
        pytest.skip("no live cache in this checkout")
    files = [p for p in LIVE_CACHE.rglob("*") if p.is_file()]
    assert len(files) == 63, f"live cache holds {len(files)} files, expected 63"


# --- G17: no CSV is committed ------------------------------------------------------------------


def test_g17_no_ffa_csv_is_tracked_by_git() -> None:
    """The repository is PUBLIC and the data is subscription-derived. This is not negotiable."""
    result = subprocess.run(
        ["git", "ls-files", "sim/data/ffa/"],
        cwd=REPO, capture_output=True, text=True, check=True,
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    assert not [t for t in tracked if t.endswith(".csv")], (
        f"a subscription-derived CSV is tracked by git: {tracked}"
    )


def test_g17_the_gitignore_rule_is_intact() -> None:
    """The rule itself, so a run cannot pass by deleting the data instead of ignoring it."""
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "sim/data/ffa/*.csv" in text, "the FFA gitignore rule was removed or weakened"


# --- what the market side blocks, recorded as a gate rather than as a remark -------------------


def test_g_the_2019_and_2020_seasons_are_blocked_by_the_market_not_the_outcome(mods) -> None:
    """REFUTES A PRIOR SESSION. `player_stats_2020` is not unavailable; it fetches cleanly.

    What blocks 2019 and 2020 is the MARKET side: no historical FFC board is pinned and this
    repository carries no fetcher for one, and the completed 6012 draft would need
    authenticated live ESPN access. Recorded as a gate so the reason cannot quietly become
    "the outcome frame does not exist" again.
    """
    _artifact, _boards, ffa, *_rest = mods
    for season in (2019, 2020):
        assert season not in ffa.SCOREABLE
        missing = [
            name
            for name in (
                f"ffc_adp_standard_8_{season}.json",
                f"espn_draft_6012_{season}.json",
            )
            if not any((root / name).exists() for root in (SIM_CACHE, LIVE_CACHE))
        ]
        assert missing, (
            f"season {season} now has its market inputs pinned; it should move into SCOREABLE"
        )
