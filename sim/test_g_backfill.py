"""FAILURE INJECTIONS for the B0 backfill. A check that cannot fail is not a check.

Three defects are injected deliberately and each gate must go red on its own:

  1. a season that does not exist        -> the fetch fails loudly and pins nothing
  2. a season truncated at week 14       -> completeness fails, NAMING season and weeks
  3. one corrupted crosswalk id          -> the ADP join miss rate MOVES

All three run offline AND without the gitignored `data/cache`, against the synthetic season
in sim/synthetic.py. That is not a convenience. Pointed at the pinned parquet, five of these
gates SKIPPED in any fresh clone and pytest still exited 0 -- the injections reported green
in exactly the case where they had tested nothing. A gate that can only fail on the one
machine that already has the data is not a gate.

The tests that genuinely need real data are kept separate at the bottom and skip honestly.

Injection 1 stands in for a 404 with a loader that raises, because a gate whose red depends
on a third-party host is not a gate either. The behaviour it models was measured directly:
``nflreadpy.load_player_stats([2099])`` raises ``ConnectionError`` on a 404, while ``[1999]``
returns a real 16,839-row frame -- nflverse carries the past back to 1999, so a "nonexistent
season" has to be a FUTURE one.

Slow-marked by sim/conftest.py like every gate here, and never in the fast suite:

    uv run pytest sim/test_g_backfill.py -m slow
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pl = pytest.importorskip("polars", reason="the backfill gates read parquet")

from .adp_join import BoardPlayer, crosswalk_index, normalize, resolve_board  # noqa: E402
from .backfill import (  # noqa: E402
    REG_GAMES,
    StaleRefresh,
    inspect_frame,
    pin_season,
)
from .synthetic import season_frame  # noqa: E402

CACHE = Path(__file__).resolve().parents[1] / "data" / "cache"
SEASON = 2024


@pytest.fixture
def complete() -> Any:
    frame = season_frame(SEASON)
    assert inspect_frame(frame, SEASON).ok, "the synthetic season must start clean"
    return frame


# --- injection 1: a season that does not exist ---------------------------------------


class _Exploding:
    """Stands in for nflreadpy when the season's release does not exist."""

    def __init__(self) -> None:
        self.calls = 0

    def load_player_stats(self, seasons: list[int], summary_level: str = "week") -> Any:
        self.calls += 1
        raise ConnectionError(
            "Failed to download .../stats_player_week_2099.parquet: 404 Client Error"
        )


def test_i1_nonexistent_season_fails_loudly_and_pins_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 404 must propagate, and must leave no file and no manifest entry behind."""
    from audible.adapters import cache as cache_mod
    from audible.adapters import nflverse

    monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", tmp_path)
    loader = _Exploding()
    monkeypatch.setattr(nflverse, "_require_nflreadpy", lambda: loader)

    with pytest.raises(ConnectionError):
        pin_season(2099)

    assert loader.calls == 1, "the loader must actually have been asked"
    nflverse_dir = tmp_path / "nflverse"
    written = list(nflverse_dir.glob("*.parquet")) if nflverse_dir.exists() else []
    assert written == [], f"a failed fetch wrote {written}"
    manifest = nflverse_dir / "manifest.json"
    if manifest.exists():
        assert "player_stats_2099" not in json.loads(manifest.read_text(encoding="utf-8"))


def test_i1_forced_refresh_that_falls_back_to_disk_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The false pass injection 1 must not hide behind.

    ``_cached`` catches EVERY exception and, when a copy is on disk, returns it as
    ``origin: disk``. That is right for draft night and wrong here: without an explicit
    check, ``--force`` against a dead host printed the same "pinned and complete" line as a
    real refresh, so injection 1 only ever proved anything about keys that were not already
    pinned. ``pin_season`` now raises instead.
    """
    from audible.adapters import cache as cache_mod
    from audible.adapters import nflverse

    monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", tmp_path)
    cache_mod.FrameCache().put(
        f"player_stats_{SEASON}", season_frame(SEASON), source="test/pinned"
    )
    monkeypatch.setattr(nflverse, "_require_nflreadpy", lambda: _Exploding())

    with pytest.raises(StaleRefresh):
        pin_season(SEASON, force=True)


def test_i1_a_failing_inspection_never_deletes_a_pin_it_did_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report, never repair.

    ``pin_season`` reads disk-first, so a season already on disk that fails inspection was
    NOT written by this run. Run from the main checkout that file is the live cockpit's
    data, and deleting it would turn a false alarm into an outage.
    """
    from audible.adapters import cache as cache_mod

    monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", tmp_path)
    truncated = season_frame(SEASON).filter(
        (pl.col("season_type") != "REG") | (pl.col("week") <= 14)
    )
    cache = cache_mod.FrameCache()
    cache.put(f"player_stats_{SEASON}", truncated, source="test/pre-existing")

    report, withdrawn = pin_season(SEASON)

    assert not report.ok, "the truncated pin should still be reported as incomplete"
    assert not withdrawn, "a pre-existing pin must not be withdrawn"
    assert cache.has(f"player_stats_{SEASON}"), "the pre-existing pin was deleted"


def test_i1_a_frame_this_run_pinned_and_then_failed_is_withdrawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: what this run wrote and could not vouch for must not survive."""
    from audible.adapters import cache as cache_mod
    from audible.adapters import nflverse

    monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", tmp_path)
    truncated = season_frame(SEASON).filter(
        (pl.col("season_type") != "REG") | (pl.col("week") <= 14)
    )

    class _Short:
        def load_player_stats(self, seasons: list[int], summary_level: str = "week") -> Any:
            return truncated

    monkeypatch.setattr(nflverse, "_require_nflreadpy", lambda: _Short())

    report, withdrawn = pin_season(SEASON)
    assert not report.ok
    assert withdrawn, "a season this run pinned and failed must be withdrawn"
    assert not cache_mod.FrameCache().has(f"player_stats_{SEASON}")


# --- injection 2: a truncated or hollowed season -------------------------------------


def test_i2_truncation_is_caught_and_names_the_missing_weeks(complete: Any) -> None:
    """Cut the season off at week 14 and the check must say which weeks went."""
    truncated = complete.filter(
        (pl.col("season_type") != "REG") | (pl.col("week") <= 14)
    )
    report = inspect_frame(truncated, SEASON)

    assert not report.ok, "a season cut at week 14 passed the completeness check"
    joined = " | ".join(report.problems)
    assert str(SEASON) in joined, f"the season is not named: {joined}"
    for week in (15, 16, 17, 18):
        assert str(week) in joined, f"missing week {week} is not named: {joined}"
    assert report.reg_games < REG_GAMES


def test_i2_a_single_missing_game_is_caught(complete: Any) -> None:
    """The subtler truncation: every week present, one game gone.

    Not hypothetical -- 2022 is genuinely one game short (the abandoned BUF@CIN), which is
    why the expected count is named per season rather than assumed to be 272 everywhere.
    """
    victim = complete.filter(pl.col("season_type") == "REG")["game_id"].to_list()[0]
    holed = complete.filter(pl.col("game_id") != victim)

    report = inspect_frame(holed, SEASON)
    assert not report.ok, f"dropping game {victim} left the season looking complete"
    joined = " | ".join(report.problems)
    assert "271" in joined and str(SEASON) in joined, joined


def test_i2_a_missing_team_is_caught(complete: Any) -> None:
    holed = complete.filter(pl.col("team") != "T00")
    report = inspect_frame(holed, SEASON)
    assert not report.ok
    assert "team" in " | ".join(report.problems).lower()


def test_i2_a_decimated_season_is_caught(complete: Any) -> None:
    """Every week and every game present, but three players per game instead of forty-four.

    Structure checks alone pass on this. It is the shape a partial upstream release takes,
    and a bootstrap drawn from it would resample a league of nobody.
    """
    thin = complete.group_by("game_id", maintain_order=True).head(3)
    report = inspect_frame(thin, SEASON)
    assert not report.ok, "a season with three rows a game passed"
    assert "rows per REG game" in " | ".join(report.problems)


def test_i2_a_quarterbacks_only_season_is_caught(complete: Any) -> None:
    """Losing every non-QB column of the release still leaves a well-shaped skeleton."""
    qbs = complete.filter(pl.col("position").is_in(["QB", "RB", "WR", "TE"]))
    report = inspect_frame(qbs, SEASON)
    assert not report.ok, "a season with no kickers passed"
    assert "position" in " | ".join(report.problems)


def test_i2_duplicated_rows_are_caught(complete: Any) -> None:
    """A double-counted week inflates a bootstrap silently."""
    doubled = pl.concat([complete, complete.filter(pl.col("week") == 3)])
    report = inspect_frame(doubled, SEASON)
    assert not report.ok, "duplicate (player, game) rows passed"
    assert "duplicate" in " | ".join(report.problems)


def test_i2_preseason_rows_are_caught(complete: Any) -> None:
    """PRE rows would be resampled as if they were games that counted."""
    pre = complete.filter(pl.col("week") == 1).with_columns(
        pl.lit("PRE").alias("season_type")
    )
    report = inspect_frame(pl.concat([complete, pre]), SEASON)
    assert not report.ok, "preseason rows passed"
    assert "season_type" in " | ".join(report.problems)


def test_i2_a_complete_season_still_passes(complete: Any) -> None:
    """The other half of every injection: the gate must not simply always be red."""
    assert inspect_frame(complete, SEASON).ok


# --- injection 3: a corrupted crosswalk id -------------------------------------------


def _tiny_join() -> tuple[list[BoardPlayer], list[dict[str, Any]], dict[str, Any]]:
    board = [
        BoardPlayer(1, "Christian McCaffrey", "RB", "SF"),
        BoardPlayer(2, "Ja'Marr Chase", "WR", "CIN"),
        BoardPlayer(3, "Kenneth Walker III", "RB", "SEA"),
        BoardPlayer(4, "Cincinnati Defense", "DEF", "CIN"),
    ]
    rows = [
        {"name": "Christian McCaffrey", "gsis_id": "00-0033280"},
        {"name": "Ja'Marr Chase", "gsis_id": "00-0036900"},
        {"name": "Kenneth Walker", "gsis_id": "00-0037746"},
    ]
    weekly = {
        "00-0033280": (17, frozenset({"RB"})),
        "00-0036900": (17, frozenset({"WR"})),
        "00-0037746": (16, frozenset({"RB"})),
    }
    return board, rows, weekly


def test_i3_corrupting_a_crosswalk_id_moves_the_miss_rate() -> None:
    """Break one id and the join must notice. A rate that cannot move measures nothing."""
    board, rows, weekly = _tiny_join()
    clean = resolve_board(board, crosswalk_index(rows), weekly)
    assert len(clean[0]) + len(clean[1]) == 0, "the clean board must resolve fully"

    corrupted = [dict(r) for r in rows]
    corrupted[1]["gsis_id"] = "00-9999999"
    dirty = resolve_board(board, crosswalk_index(corrupted), weekly)

    assert len(dirty[0]) + len(dirty[1]) == 1, "corrupting an id did not move the miss count"
    assert "Ja'Marr Chase" in dirty[1][0]


def test_i3_a_MISDIRECTED_id_is_invisible_to_a_miss_rate() -> None:
    """The honest limit of injection 3, pinned so nobody mistakes G3 for more than it is.

    A miss rate counts players who reach NO row. Repointing one player's crosswalk entry at
    another real player's gsis_id still reaches a row, so the rate does not move at all --
    it just silently attributes the wrong season. G3 measures reachability, never
    correctness of attribution, and only the same-name collision guard below defends that.
    """
    board, rows, weekly = _tiny_join()
    baseline = resolve_board(board, crosswalk_index(rows), weekly)

    misdirected = [dict(r) for r in rows]
    misdirected[1]["gsis_id"] = misdirected[0]["gsis_id"]  # Chase now points at McCaffrey
    after = resolve_board(board, crosswalk_index(misdirected), weekly)

    assert len(after[0]) + len(after[1]) == len(baseline[0]) + len(baseline[1]), (
        "if a misdirected id DID move the miss rate, this limitation is fixed and the "
        "docstring above is wrong"
    )


def test_i3_suffix_stripping_collision_is_caught_not_guessed() -> None:
    """Suffix stripping is load-bearing AND dangerous -- this is the collision it creates.

    Stripping suffixes is what makes FFC's "Kenneth Walker" meet nflverse's "Kenneth
    Walker III". The same step collapses Michael Carter II, a Jets cornerback, onto Michael
    Carter, a Jets running back, and both played 2021. Position has to break that tie;
    without it a replay would credit a corner's weeks to a drafted RB.
    """
    assert normalize("Michael Carter II") == normalize("Michael Carter")

    board = [BoardPlayer(1, "Michael Carter", "RB", "NYJ")]
    rows = [
        {"name": "Michael Carter", "gsis_id": "00-0036924"},
        {"name": "Michael Carter II", "gsis_id": "00-0036925"},
    ]
    weekly = {
        "00-0036924": (14, frozenset({"RB"})),
        "00-0036925": (15, frozenset({"CB"})),
    }
    stage1, stage2, ambiguous, hits = resolve_board(board, crosswalk_index(rows), weekly)
    assert hits == 1 and not ambiguous, f"the collision was not resolved: {ambiguous}"

    # And when position CANNOT break it, the join must say so rather than pick one.
    both_rb = {k: (v[0], frozenset({"RB"})) for k, v in weekly.items()}
    _, _, still_ambiguous, _ = resolve_board(board, crosswalk_index(rows), both_rb)
    assert still_ambiguous, "an unresolvable collision was silently guessed at"


# --- the same gates against the real pinned data, where it exists ---------------------


def _pinned(season: int) -> Any:
    path = CACHE / "nflverse" / f"player_stats_{season}.parquet"
    if not path.exists():
        pytest.skip(f"{path} is not pinned; run `python -m sim.backfill` first")
    return pl.read_parquet(path)


@pytest.mark.parametrize("season", [2021, 2022, 2023, 2024, 2025])
def test_real_seasons_are_complete(season: int) -> None:
    report = inspect_frame(_pinned(season), season)
    assert report.ok, f"{season}: {report.problems}"


def test_real_2022_is_short_exactly_one_game_and_says_why() -> None:
    """The one season that is not 272 games, and the reason it is right not to be."""
    report = inspect_frame(_pinned(2022), 2022)
    assert report.ok and report.reg_games == 271
    assert "Hamlin" in report.note
