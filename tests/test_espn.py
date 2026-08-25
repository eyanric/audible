"""ESPN adapter -- offline, against a trimmed capture of the live league (id 6012).

The fixture is a real ``kona_player_info`` response plus the league's real
``scoringItems``, cut down to fourteen players spanning every scoring path. Refresh it
from live when the API shifts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from audible.adapters.espn import (
    SOURCE_SPECIALIST,
    SOURCE_STAT_LINE,
    EspnAdapter,
    EspnAuthError,
    EspnDataError,
    translate_stat_line,
)
from audible.config import LeagueConfig
from audible.scoring.engine import score_stat_line

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ESPN pays statId 63 -- an offensive fumble recovered for a touchdown -- 6.0 points, and
# our config has no key for it. It is the entire difference between our recomputation and
# ESPN's own applied total: 0.233 pts on a 368-pt QB season, the largest case in the pool.
UNMAPPED_STAT_63_TOLERANCE = 0.25


@pytest.fixture(scope="module")
def sample() -> dict[str, Any]:
    return json.loads((FIXTURES / "espn_league_sample.json").read_text(encoding="utf-8"))


def _player(sample: dict[str, Any], name: str) -> dict[str, Any]:
    for row in sample["players"]:
        if row["player"]["fullName"] == name:
            return row["player"]
    raise AssertionError(f"{name} is not in the fixture")


def _line(sample: dict[str, Any], name: str) -> tuple[dict[str, Any], float]:
    """(raw {statId: value} projection, ESPN's own applied total) for *name*."""
    stat_set = _player(sample, name)["stats"][0]
    return stat_set["stats"], float(stat_set["appliedTotal"])


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> EspnAdapter:
    """An adapter with credentials and a mock transport -- never touches the network."""
    return EspnAdapter(
        swid="{TEST-SWID}", espn_s2="test-s2", transport=httpx.MockTransport(handler)
    )


def _serving(sample: dict[str, Any], players: list[Any] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if "mSettings" in request.url.params.get_list("view"):
            settings = {"scoringSettings": {"scoringItems": sample["scoringItems"]}}
            return httpx.Response(200, json={"settings": settings})
        pool = sample["players"] if players is None else players
        return httpx.Response(200, json={"players": pool})

    return handler


# --- the QB bucket path ---------------------------------------------------------------


def test_qb_passing_yards_come_from_the_bucketed_stat(sample: dict[str, Any]) -> None:
    """League 6012 pays passing yards via statId 8 (one point per completed 25 yards).

    Reading statId 3 instead would score yards ESPN does not pay for -- statId 3 is not a
    scoring item in this league at all -- and would run every QB high.
    """
    raw, _ = _line(sample, "Josh Allen")
    assert raw["8"] == 157.0
    assert raw["3"] == pytest.approx(3944.731641)

    stats = translate_stat_line(raw, "QB")
    assert stats["pass_yd"] == 157.0 * 25  # 3925, the floored bucket -- not 3944.73
    assert stats["pass_yd"] < raw["3"], "the bucket floors partial 25-yard increments away"


def test_qb_recomputation_matches_espns_own_total(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The load-bearing check: our arithmetic, ESPN's answer.

    If the bucket conversion were wrong in either direction this is what would catch it --
    scoring statId 8 raw would be ~157 pts low, scoring statId 3 would be ~0.8 pts high.
    """
    raw, espn_total = _line(sample, "Josh Allen")
    ours = score_stat_line(translate_stat_line(raw, "QB"), espn_config.scoring_for("QB"))
    assert ours == pytest.approx(espn_total, abs=UNMAPPED_STAT_63_TOLERANCE)


def test_qb_falls_back_to_raw_yards_when_the_bucket_disappears(sample: dict[str, Any]) -> None:
    """A QB projected to throw for nothing looks like data, not like a break."""
    raw, _ = _line(sample, "Josh Allen")
    without_bucket = {k: v for k, v in raw.items() if k != "8"}
    assert translate_stat_line(without_bucket, "QB")["pass_yd"] == pytest.approx(3944.731641)


# --- the position-scoped reception split ------------------------------------------------


def test_receptions_split_rb_from_wr(sample: dict[str, Any], espn_config: LeagueConfig) -> None:
    """The commissioner pays WR/TE 0.5 per reception and RB zero, deliberately.

    ESPN's own applied total is computed under that rule, so reconciling a pass-catching
    back against it is what proves the split is wired -- scoring him on WR weights would
    land ~34 points high and quietly reorder RB against WR at the top of the board.
    """
    raw, espn_total = _line(sample, "Jahmyr Gibbs")
    stats = translate_stat_line(raw, "RB")
    receptions = stats["rec"]
    assert receptions > 60, "fixture must hold a genuinely pass-catching back"

    as_rb = score_stat_line(stats, espn_config.scoring_for("RB"))
    as_wr = score_stat_line(stats, espn_config.scoring_for("WR"))

    assert as_rb == pytest.approx(espn_total, abs=UNMAPPED_STAT_63_TOLERANCE)
    assert as_wr - as_rb == pytest.approx(0.5 * receptions)


def test_wr_is_paid_for_receptions(sample: dict[str, Any], espn_config: LeagueConfig) -> None:
    raw, espn_total = _line(sample, "Ja'Marr Chase")
    stats = translate_stat_line(raw, "WR")
    ours = score_stat_line(stats, espn_config.scoring_for("WR"))
    assert ours == pytest.approx(espn_total, abs=UNMAPPED_STAT_63_TOLERANCE)
    # Zeroing his receptions must cost exactly half a point each -- i.e. he is being paid.
    without = score_stat_line({**stats, "rec": 0.0}, espn_config.scoring_for("WR"))
    assert ours - without == pytest.approx(0.5 * stats["rec"])


# --- the empty pool -------------------------------------------------------------------


def test_empty_pool_raises_instead_of_becoming_an_empty_board(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """Drop `sortDraftRanks` and ESPN answers 200 with zero players and no error. Returning
    that reads downstream as "nobody is available" -- it has to fail here instead."""
    with _adapter(_serving(sample, players=[])) as adapter, pytest.raises(EspnDataError) as exc:
        adapter.get_player_pool(espn_config)
    assert "sortDraftRanks" in str(exc.value)


def test_pool_request_always_sorts_by_draft_rank(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The sort is the whole reason the endpoint answers with players at all."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _serving(sample)(request)

    with _adapter(handler) as adapter:
        adapter.get_player_pool(espn_config)

    payload = json.loads(seen[-1].headers["X-Fantasy-Filter"])
    assert payload["players"]["sortDraftRanks"]["value"] == "STANDARD"
    assert payload["players"]["limit"] > 1026, "the limit is a guard, not a cap on the pool"
    # Private league: without both cookies ESPN answers 401 for every one of these views.
    cookies = seen[-1].headers["cookie"]
    assert "SWID={TEST-SWID}" in cookies and "espn_s2=test-s2" in cookies


# --- credentials ----------------------------------------------------------------------


def test_expired_cookies_say_what_to_do(sample: dict[str, Any], espn_config: LeagueConfig) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    with _adapter(handler) as adapter, pytest.raises(EspnAuthError) as exc:
        adapter.get_player_pool(espn_config)
    assert "re-pull cookies" in str(exc.value)


def test_missing_cookies_never_reach_the_network(espn_config: LeagueConfig) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request may be made without credentials")

    adapter = EspnAdapter(swid="", espn_s2="", transport=httpx.MockTransport(handler))
    with adapter, pytest.raises(EspnAuthError) as exc:
        adapter.get_player_pool(espn_config)
    assert "ESPN_SWID" in str(exc.value)


# --- the whole universe ----------------------------------------------------------------


def test_projections_score_offense_and_defer_specialists(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    with _adapter(_serving(sample)) as adapter:
        players = adapter.player_projections(espn_config)
        counts = adapter.source_counts

    assert adapter.pool_size == len(sample["players"])
    assert counts[SOURCE_STAT_LINE] == 10  # 2 QB + 3 RB + 3 WR + 2 TE
    assert counts[SOURCE_SPECIALIST] == 4  # 2 K + 2 D/ST -- no translation exists

    by_name = {p.name: p for p in players}
    assert by_name["Texans D/ST"].primary_position == "DEF"
    assert by_name["Brandon Aubrey"].primary_position == "K"
    # Specialists carry ESPN's number unchanged; scoring them through our engine would
    # silently produce 0 and drop both positions off the board entirely.
    assert by_name["Texans D/ST"].points == pytest.approx(147.72439963)
    assert by_name["Brandon Aubrey"].points == pytest.approx(168.55428688)

    allen = by_name["Josh Allen"]
    assert allen.team == "BUF"
    assert allen.points == pytest.approx(368.41909807, abs=UNMAPPED_STAT_63_TOLERANCE)
    assert allen.stats["espn_draft_rank"] == 36.0

    # A RUNNING BACK, on this path, deliberately. Every other assertion here is a QB, a
    # kicker or a D/ST -- none of which the reception rule touches -- so this test used to
    # pass unchanged with `scoring_by_position` deleted, while every back in the league ran
    # ~34 points a season high. `test_receptions_split_rb_from_wr` covers the same
    # arithmetic but calls `score_stat_line` directly; only this one proves the adapter
    # hands `player_projections` a POSITION rather than resolving the base table.
    gibbs = by_name["Jahmyr Gibbs"]
    assert gibbs.stats["rec"] == pytest.approx(67.80887914)
    assert gibbs.points == pytest.approx(297.39338, abs=UNMAPPED_STAT_63_TOLERANCE)


def test_the_adapter_scores_backs_through_the_position_scoped_table(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """Strip the override and every back must move -- proof the adapter passes a position.

    Pinning the corrected number alone is not enough: it would still pass if the fixture
    happened to agree. Scoring the same pool off the base table has to change the answer,
    and only for the backs.
    """
    flat = espn_config.model_copy(update={"scoring_by_position": {}})
    with _adapter(_serving(sample)) as adapter:
        correct = {p.name: p for p in adapter.player_projections(espn_config)}
    with _adapter(_serving(sample)) as adapter:
        base_table = {p.name: p for p in adapter.player_projections(flat)}

    moved = {
        name: base_table[name].points - p.points
        for name, p in correct.items()
        if base_table[name].points != p.points
    }
    assert {correct[name].primary_position for name in moved} == {"RB"}, (
        f"only running backs may move when the RB reception override is removed: {moved}"
    )
    for name, delta in moved.items():
        assert delta == pytest.approx(correct[name].stats["rec"] * 0.5), name


# --- scoring drift --------------------------------------------------------------------


def test_verify_scoring_is_quiet_against_the_live_table(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """Committed config vs the league's real scoringItems: 48 position-scoped weights.

    This passes only because the comparison reads `pointsOverrides` per position. ESPN
    encodes receptions as base 0.0 with QB/WR/TE overrides; our config says base 0.5 with
    an RB override. Comparing base against base would report drift where there is none.
    """
    with _adapter(_serving(sample)) as adapter:
        assert adapter.verify_scoring(espn_config) == []


def test_verify_scoring_catches_a_ppr_flip_back_to_standard(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The league's standing risk: League B was standard until the commissioner flipped it."""
    reverted = json.loads(json.dumps(sample))
    for item in reverted["scoringItems"]:
        if item["statId"] == 53:
            item["pointsOverrides"] = {}

    with _adapter(_serving(reverted)) as adapter:
        drift = dict.fromkeys(key for key, _, _ in adapter.verify_scoring(espn_config))
        live_rec = adapter.live_reception_points(espn_config)

    assert "rec[WR]" in drift and "rec[TE]" in drift
    assert "rec[RB]" not in drift, "RB is paid zero in both encodings -- that is not drift"
    assert live_rec == 0.0


def test_live_reception_points_reads_the_position_override(
    sample: dict[str, Any], espn_config: LeagueConfig
) -> None:
    with _adapter(_serving(sample)) as adapter:
        assert adapter.live_reception_points(espn_config, "WR") == 0.5
        assert adapter.live_reception_points(espn_config, "TE") == 0.5
        # RB is absent from the overrides and so falls back to the base 0.0 -- by design.
        assert adapter.live_reception_points(espn_config, "RB") == 0.0
