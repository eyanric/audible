from __future__ import annotations

import json
from pathlib import Path

import pytest

from audible.crosswalk import Crosswalk
from audible.models import RawPlayerLine

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def id_map_rows() -> list[dict[str, object]]:
    return json.loads((FIXTURES / "ff_playerids_sample.json").read_text())


def _line(pid: str, pos: str = "RB", gsis: str | None = None) -> RawPlayerLine:
    ids = {"gsis_id": gsis} if gsis else {}
    return RawPlayerLine(
        player_id=pid, name=pid, primary_position=pos,
        eligible_positions=frozenset({pos}), team=None, ids=ids,
    )


def test_catalog_gsis_wins_without_join(id_map_rows: list[dict[str, object]]) -> None:
    xwalk = Crosswalk(id_map_rows)
    resolved = xwalk.resolve(_line("4984", "QB", gsis="00-0000000"))
    assert resolved.source == "catalog"
    assert resolved.gsis_id == "00-0000000"


def test_ff_playerids_fallback_when_catalog_lacks_gsis(
    id_map_rows: list[dict[str, object]]
) -> None:
    # Josh Allen (sleeper 4984) has a gsis_id in the ff_playerids fixture.
    xwalk = Crosswalk(id_map_rows)
    resolved = xwalk.resolve(_line("4984", "QB"))
    assert resolved.source == "ff_playerids"
    assert resolved.gsis_id is not None and resolved.matched


def test_team_defense_is_unmatched(id_map_rows: list[dict[str, object]]) -> None:
    # Team D/ST (sleeper id = team abbrev) has no gsis and isn't in the crosswalk.
    xwalk = Crosswalk(id_map_rows)
    resolved = xwalk.resolve(_line("LAR", "DEF"))
    assert resolved.source == "unmatched"
    assert not resolved.matched


def test_report_aggregates(id_map_rows: list[dict[str, object]]) -> None:
    xwalk = Crosswalk(id_map_rows)
    report = xwalk.resolve_all(
        [_line("4984", "QB", gsis="00-1"), _line("9509", "RB"), _line("HOU", "DEF")]
    )
    counts = report.source_counts()
    assert counts == {"catalog": 1, "ff_playerids": 1, "unmatched": 1}
    assert report.match_rate == pytest.approx(2 / 3)
    assert len(report.unmatched) == 1


def test_blank_ids_in_id_map_are_ignored() -> None:
    xwalk = Crosswalk([{"sleeper_id": "1", "gsis_id": ""}, {"sleeper_id": None, "gsis_id": "x"}])
    assert xwalk.resolve(_line("1")).source == "unmatched"
