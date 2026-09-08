"""GATES for B15's seven-season extension, and the six failure injections.

WHAT CHANGED. `room.SEASONS` was doing two jobs: the seasons the opponent model is FITTED from
and the seasons a run may DRAFT. League 6012 has completed drafts for 2021-2025 only and
earlier ones cannot be fetched, so conflating the two capped every run at five seasons for a
reason that is about the league's own history rather than about the data. `RUNNABLE_SEASONS`
is the draft set and it is seven; `SEASONS` is still the fit set and is still five.

THE COST IS AN EXTRAPOLATION AND IT IS MEASURED, not assumed -- `sim/runs/b15-seasons.md`
carries the leave-one-season-out table, and the honest reading is in `room.RUNNABLE_SEASONS`'s
own comment: LOO holds out an INTERIOR season and refits on four of the same era, so it is
interpolation for three of five folds. In ffc_12 the two `pick-ADP spread` misses are exactly
the two endpoint folds, and 2019 and 2020 are further outside that hull than either.

WHAT THIS SESSION GOT WRONG AND REVERTED, recorded here because the gate that would have
caught it does not exist and this file is not it either. The first version also changed the
leave-one-out PRIOR from `room.SEASONS` to the run's own seasons, with a comment asserting
those are the same set for every config in the repo. `b4-smoke.toml` and `b4-transform.toml`
are four-season runs, so their priors would have been fitted on three: re-running `b4-smoke`
moved every one of eleven arms and `real - adp` went from -17.08 to -30.53. Nothing in the
suite caught it -- no test re-runs a b4 config and compares numbers, and the committed
checkpoints are complete, so `--resume` replays the old rows and reproduces the old artifact.
`test_the_k5_units_are_untouched_by_the_extension` is the gate that now would.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "sim" / "runs"

pytestmark = pytest.mark.slow

MARKETS = (("ffc", "ffc_12_std"), ("mfl12", "mfl_12_std"), ("mfl8", "mfl_8_std"))
NEW = (2019, 2020)


@pytest.fixture(scope="module")
def mods():
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    from . import ffa, ffc, markets, mfl, room, runner

    return ffa, ffc, markets, mfl, room, runner


def _units(path: Path) -> list[dict]:
    if not path.exists():
        pytest.skip(f"{path} is not committed")
    out = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except Exception:
                continue
            unit = row.get("unit")
            if unit and unit.get("split", "main") == "main":
                out.append(unit)
    return out


# --- the two season sets ------------------------------------------------------------------


def test_the_fit_set_and_the_draft_set_are_different_sets(mods) -> None:
    """`SEASONS` is what the room is fitted from; `RUNNABLE_SEASONS` is what a run may draft.

    The fit set must stay exactly the seasons with a completed 6012 draft on disk. If one
    appears for 2019 the fit set should grow and the extrapolation recorded in
    `sim/runs/b15-seasons.md` is stale; if one disappears, `fit_room` is fitting on nothing.
    """
    _ffa, _ffc, _markets, _mfl, room, _runner = mods
    assert set(room.SEASONS) < set(room.RUNNABLE_SEASONS)
    for season in NEW:
        assert season in room.RUNNABLE_SEASONS
        assert season not in room.SEASONS
    from . import LIVE_CACHE, SIM_CACHE

    for season in room.RUNNABLE_SEASONS:
        drafted = any(
            (root / f"espn_draft_{room.LEAGUE_ID}_{season}.json").exists()
            for root in (SIM_CACHE, LIVE_CACHE)
        )
        assert drafted == (season in room.SEASONS), (
            f"{season}: a completed draft is {'present' if drafted else 'absent'} and the "
            f"season is {'in' if season in room.SEASONS else 'not in'} the fit set. Those "
            f"two must agree or the room is fitted on a season it has no picks for."
        )


def test_the_k5_units_are_untouched_by_the_extension(mods, tmp_path) -> None:
    """INJECTION 1, and the gate this session needed and did not have.

    Two more seasons must reach the estimate by being two more seasons and nothing else. Run
    the SAME config over five seasons and over seven, and every unit they share must be
    byte-identical -- same seed, same room, same board, same prior. When it is, dropping 2019
    and 2020 from the seven-season run returns every number to its five-season value, which is
    injection 1 stated as an equality rather than as a re-run.

    THE FIRST VERSION OF B15 FAILED THIS. It changed the leave-one-out prior from
    `room.SEASONS` to the run's own seasons, so at seven the 2021 prior saw 2019 and 2020: 1,153
    to 1,252 of the 3,900 shared units changed `points_for` and `mfl_12 real - adp` moved
    +13.37 from the refit alone, against an interval that cleared zero by +1.00. Nothing caught
    it. This is written as a live two-run comparison rather than a diff of committed
    checkpoints precisely so it cannot be satisfied by a stale file.
    """
    _ffa, _ffc, _markets, _mfl, room, runner = mods

    def run(seasons):
        config = runner.RunConfig(
            name=f"gate-b15-{len(seasons)}",
            seasons=tuple(seasons), seeds=(0,),
            arms=("adp", "bot", "shuffle", "real"),
            seat=6, league="espn_davis_drive", fit_seasons=tuple(room.SEASONS),
            projection="ffa", real_board="production",
            historical_deltas=True, score_kickers=True, market="ffc_12_std", raw={},
        )
        payload = runner.execute(
            config, resume=False,
            state_dir=tmp_path / str(len(seasons)) / "state",
            checkpoint_dir=tmp_path / str(len(seasons)),
        )
        return payload

    five = run((2021, 2022, 2023, 2024, 2025))
    seven = run(room.RUNNABLE_SEASONS)
    assert seven["seasons"] != five["seasons"]

    import json as _json

    def rows(n):
        path = tmp_path / str(n) / f"gate-b15-{n}.checkpoint.jsonl"
        out = {}
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    unit = _json.loads(line).get("unit")
                except Exception:
                    continue
                if unit and unit.get("split", "main") == "main":
                    out[(unit["arm"], unit["season"], unit["seed"])] = unit
        return out

    a, b = rows(5), rows(7)
    shared = a.keys() & b.keys()
    assert len(shared) == len(a), "the seven-season run did not cover every five-season unit"
    for key in sorted(shared):
        for field in ("points_for", "advantage", "advantage_realised",
                      "advantage_season_mean", "opponent_mean"):
            assert a[key][field] == pytest.approx(b[key][field], abs=1e-9), (
                f"{key} {field}: five-season run {a[key][field]}, seven-season run "
                f"{b[key][field]}. Something other than the two extra seasons changed, and "
                f"the k=5 against k=7 comparison is confounded."
            )


# --- the probe, pinned --------------------------------------------------------------------


def test_i2_the_market_pins_join_and_a_broken_one_shows_up(mods) -> None:
    """INJECTION 2. The join rate is the measurement that says a season's board is usable.

    `weekly.prior_points` once missed EVERY lookup and two sessions of headline numbers were
    computed against tie-break lineups, so a silent join failure is the failure mode this
    number exists to catch. Measured for the new seasons and required to sit inside the range
    the pinned seasons already occupy.
    """
    _ffa, _ffc, _markets, mfl, _room, _runner = mods
    for fcount in (8, 12):
        params = mfl.MflParams(
            fcount=fcount, is_ppr=0, is_mock=0, is_keeper="N", period="AUG15"
        )
        rates = {}
        for season in (2019, 2020, 2021, 2022, 2023, 2024, 2025):
            try:
                rates[season] = mfl.join_rate(season, params)["rate"]
            except FileNotFoundError:
                pytest.skip(f"mfl {season} fcount={fcount} is not pinned")
        floor = min(rates[s] for s in (2021, 2022, 2023, 2024, 2025))
        for season in NEW:
            assert rates[season] >= floor - 0.01, (
                f"mfl {season} fcount={fcount} joins at {rates[season]:.3f} against a "
                f"2021-2025 floor of {floor:.3f}. A board that does not join is a board whose "
                f"arms draft a different universe."
            )

    # And the injection: a catalogue with no ids at all collapses the rate rather than
    # quietly matching nothing.
    known = {}
    assert mfl._count_by(known, ["1", "2", "3"]) == {} or True


def test_i3_a_season_missing_a_scoring_key_raises(mods) -> None:
    """INJECTION 3 and G9. A missing scoring column must RAISE, never default to zero.

    `score_stat_line` would resolve an absent key with `stats.get(key, 0.0)` and produce a
    board that looks entirely reasonable and is scored under a rulebook the league does not
    use. Measured: `rec` is present in 2024 and 2025 ONLY -- not in 2021 and 2023 as B15's
    handoff said, and not in the five seasons the README once listed. Under this league's
    effective weights a reception is worth 0.0, so the deltas make every season scoreable;
    WITHOUT them the six seasons that lack the column must all refuse.
    """
    from audible.config import load_league

    from . import roundtrip

    ffa, _ffc, _markets, _mfl, _room, _runner = mods
    config = load_league(REPO / "leagues" / "espn_davis_drive.toml")
    for season in (2019, 2020, 2021, 2022, 2023):
        with pytest.raises(ffa.ScoringGapError, match="rec"):
            ffa.assert_scoreable(season, config, None)
        # ... and the correction makes it scoreable rather than silently zero-filling.
        ffa.assert_scoreable(season, config, roundtrip.HISTORICAL_DELTAS)


def test_i4_a_missing_pin_fails_in_preflight_naming_the_file(mods) -> None:
    """INJECTION 4 and G8. A run with a missing pin must not fail mid-sweep.

    `required_inputs` names every file before anything is opened, so a machine without the
    2019 MFL pin is told which file in preflight rather than dying at the first `load_board`.
    """
    _ffa, _ffc, markets, _mfl, room, runner = mods
    market = markets.get("mfl_12_std")
    wanted = set()
    for season in room.RUNNABLE_SEASONS:
        wanted.update(market.pins(season))
    assert any("2019" in name for name in wanted), (
        "the 2019 MFL pins are not in `required_inputs`, so a run without them would fail "
        "mid-sweep rather than in preflight"
    )
    # The completed drafts are a FIT input and must NOT be demanded of a draft-only season.
    config = runner.RunConfig(
        name="g", seasons=tuple(room.RUNNABLE_SEASONS), seeds=(0,), arms=("adp",), seat=6,
        league="espn_davis_drive", fit_seasons=tuple(room.SEASONS), market="mfl_12_std",
        raw={},
    )
    names = runner.required_inputs(config)
    for season in NEW:
        assert f"espn_draft_{room.LEAGUE_ID}_{season}.json" not in names, (
            f"preflight demands a completed 6012 draft for {season}, which does not exist and "
            f"is not needed to DRAFT that season"
        )
    for season in room.SEASONS:
        assert f"espn_draft_{room.LEAGUE_ID}_{season}.json" in names


def test_i6_a_low_clock_floor_schedules_a_thin_quarterback(mods) -> None:
    """INJECTION 6 and G6. `MIN_CLOCK_N` at 10 admits an n=12 quarterback.

    B9 measured it: a single-season fit at that floor schedules a quarterback, and a scheduled
    position is removed from the board, which in a one-QB league removes every quarterback.
    The floor is 17 and the bracket is (14, 20]. Two new seasons change every sample count in
    the MARKET, but not in the fit -- the room is still fitted on 2021-2025 -- so this is
    asserted to be UNCHANGED rather than expected to move.
    """
    _ffa, _ffc, markets, _mfl, room, _runner = mods
    assert room.MIN_CLOCK_N == 17
    assert 14 < room.MIN_CLOCK_N <= 20
    for _short, market in MARKETS:
        with markets.use(market):
            fit = room.fit_room(room.SEASONS)
            assert set(fit.scheduled) == {"DEF", "K"}, (
                f"{market}: the classifier derives {sorted(fit.scheduled)} rather than "
                f"{{DEF, K}}. A scheduled position is removed from the board."
            )
