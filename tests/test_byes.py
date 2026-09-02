"""Bye weeks: the derivation's self-check, the join, and the guarantees around it.

Unlike the injury sidecar in C2, there is a real join here — so the inertness test can
actually fail, and it is written to.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any

import pytest

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import Pick
from audible.draft.service import CockpitService
from audible.server import state as state_mod
from audible.server.state import (
    BYE_WINDOW,
    _bye_collisions,
    _player,
    build_state,
    bye_consistency,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "audible"

TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]


def _schedule(byes: dict[str, int], weeks: int = 18) -> list[dict[str, Any]]:
    """A synthetic but ARITHMETICALLY HONEST season: every team plays unless on bye."""
    rows: list[dict[str, Any]] = []
    for week in range(1, weeks + 1):
        playing = [t for t in TEAMS if byes.get(t) != week]
        for i in range(0, len(playing) - 1, 2):
            rows.append({
                "game_type": "REG", "week": week,
                "home_team": playing[i], "away_team": playing[i + 1],
            })
    return rows


class _Frame:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def iter_rows(self, named: bool = False) -> list[dict[str, Any]]:
        return self._rows


@pytest.fixture(autouse=True)
def _clear_bye_cache():
    state_mod._bye_cache = None
    yield
    state_mod._bye_cache = None


def _patch_schedule(monkeypatch, rows: list[dict[str, Any]]) -> None:
    import audible.adapters.nflverse as nflverse

    monkeypatch.setattr(nflverse, "schedules_frame", lambda seasons: _Frame(rows))


# --- the self-check ---------------------------------------------------------------

def _even_byes() -> dict[str, int]:
    """Two teams per bye week over weeks 5-14, so each week keeps an even count."""
    weeks = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
    return {team: weeks[i // 2 % len(weeks)] for i, team in enumerate(TEAMS)}


def test_a_sound_schedule_passes_all_four(monkeypatch):
    _patch_schedule(monkeypatch, _schedule(_even_byes()))
    report = bye_consistency(2026)
    assert (report["b1"], report["b2"], report["b3"], report["b4"]) == (True, True, True, True)
    assert report["ok"] is True
    assert report["teams"] == 32


def test_b1_fails_when_a_team_is_missing_entirely(monkeypatch):
    rows = [r for r in _schedule(_even_byes())
            if r["home_team"] != "ARI" and r["away_team"] != "ARI"]
    _patch_schedule(monkeypatch, rows)
    report = bye_consistency(2026)
    assert report["b1"] is False
    assert report["ok"] is False


def test_b2_fails_when_a_team_has_two_byes(monkeypatch):
    rows = [r for r in _schedule(_even_byes())
            if not (r["week"] == 3 and "BUF" in (r["home_team"], r["away_team"]))]
    _patch_schedule(monkeypatch, rows)
    report = bye_consistency(2026)
    assert report["b2"] is False
    assert "BUF" in report["multi_bye"]
    assert report["ok"] is False


def test_b3_fails_when_a_bye_sits_outside_the_window(monkeypatch):
    byes = _even_byes()
    byes["KC"] = 2  # week 2 is outside weeks 4-14
    _patch_schedule(monkeypatch, _schedule(byes))
    report = bye_consistency(2026)
    assert report["b3"] is False
    assert report["outside_window"].get("KC") == 2
    assert report["ok"] is False


def test_a_dropped_game_is_caught_by_b2_not_b4(monkeypatch):
    """Worth stating explicitly, because the intuitive expectation is wrong.

    Removing a game does not unbalance B4: the two teams simply stop appearing that week,
    so `playing` shrinks in step with `games` and the arithmetic still ties. What it does
    produce is two teams with a SECOND bye, which is exactly what B2 exists to catch. The
    two checks cover different failures, and only together do they cover this one.
    """
    rows = _schedule(_even_byes())
    week1 = [i for i, r in enumerate(rows) if r["week"] == 1]
    dropped = rows.pop(week1[0])
    _patch_schedule(monkeypatch, rows)
    report = bye_consistency(2026)
    assert report["b4"] is True, "B4 stays balanced -- this is the point of the test"
    assert report["b2"] is False
    assert set(report["multi_bye"]) == {dropped["home_team"], dropped["away_team"]}
    assert report["ok"] is False


def test_b4_fails_when_a_team_is_booked_twice_in_one_week(monkeypatch):
    """The failure B4 uniquely catches: more games than distinct teams can account for."""
    rows = _schedule(_even_byes())
    wk1 = [r for r in rows if r["week"] == 1]
    # Re-home one week-1 game onto a team already playing that week.
    rows.append({"game_type": "REG", "week": 1,
                 "home_team": wk1[0]["home_team"], "away_team": wk1[1]["away_team"]})
    _patch_schedule(monkeypatch, rows)
    report = bye_consistency(2026)
    assert report["b4"] is False
    assert 1 in report["week_mismatch"]
    assert report["ok"] is False


def test_the_window_is_a_plausibility_bound_not_a_calendar():
    assert list(BYE_WINDOW) == list(range(4, 15))


# --- refusing to answer when the derivation is unsound ----------------------------

def test_a_failed_check_serves_no_byes_at_all(monkeypatch):
    """A wrong bye is worse than no bye: on failure the column disappears entirely."""
    byes = _even_byes()
    byes["KC"] = 2
    _patch_schedule(monkeypatch, _schedule(byes))
    assert state_mod.bye_weeks(2026) == {}


def test_a_broken_source_serves_no_byes_and_does_not_raise(monkeypatch):
    import audible.adapters.nflverse as nflverse

    def boom(seasons):
        raise RuntimeError("nflverse is down")

    monkeypatch.setattr(nflverse, "schedules_frame", boom)
    assert state_mod.bye_weeks(2026) == {}


def test_the_rams_alias_is_applied(monkeypatch):
    """nflverse says LA; the board says LAR. The payload must speak the board's language."""
    _patch_schedule(monkeypatch, _schedule(_even_byes()))
    byes = state_mod.bye_weeks(2026)
    assert "LAR" in byes
    assert "LA" not in byes


# --- the join ---------------------------------------------------------------------

POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]


def _entry(i: int, team: str = "BUF") -> DraftEntry:
    pos = POSITIONS[(i - 1) % len(POSITIONS)]
    return DraftEntry(
        player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
        eligible_positions=frozenset({pos}), team=team, model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=False, scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i), adp_rank=i, value=0, flags=(),
    )


@pytest.fixture
def service(tmp_path: Path, sleeper_config: LeagueConfig) -> CockpitService:
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard(
        "sleeper_boyfun",
        [_entry(i, "BUF" if i % 2 else "KC") for i in range(1, 61)],
    )
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = 4
    svc.session.slot_source = "override"
    svc.health.last_success = time.time()
    return svc


def test_the_row_gains_exactly_one_field(service):
    from audible.draft.live import Candidate

    cand = Candidate(entry=_entry(1, "BUF"), survival=0.5, grab_now=False, fills_need=False)
    without = _player(cand, {}, {})
    with_bye = _player(cand, {}, {"BUF": 7})
    assert set(with_bye) - set(without) == set(), "the key exists either way"
    assert without["bye"] is None
    assert with_bye["bye"] == 7
    assert {k: v for k, v in without.items() if k != "bye"} == {
        k: v for k, v in with_bye.items() if k != "bye"
    }


def test_an_unknown_team_yields_none_not_a_guess(service):
    from audible.draft.live import Candidate

    cand = Candidate(entry=_entry(1, "XXX"), survival=0.5, grab_now=False, fills_need=False)
    assert _player(cand, {}, {"BUF": 7})["bye"] is None


# --- INERTNESS: the board must not move because byes joined ----------------------

def _strip_byes(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for key in ("grab_now", "best_available"):
        out[key] = [{k: v for k, v in row.items() if k != "bye"} for k in [0]
                    for row in payload.get(key, [])]
    out.pop("bye_collisions", None)
    return out


def test_the_board_is_byte_identical_with_and_without_the_bye_join(service, monkeypatch):
    """Hard stop 2, made checkable. Every number must be untouched by the join."""
    _patch_schedule(monkeypatch, _schedule(_even_byes()))
    with_byes = build_state(service)

    state_mod._bye_cache = None
    monkeypatch.setattr(state_mod, "bye_weeks", lambda season: {})
    without = build_state(service)

    for key in ("grab_now", "best_available"):
        assert len(with_byes[key]) == len(without[key])
        for a, b in zip(with_byes[key], without[key], strict=True):
            assert a["bye"] is not None or b["bye"] is None
            assert {k: v for k, v in a.items() if k != "bye"} == \
                   {k: v for k, v in b.items() if k != "bye"}, \
                   "a value changed because byes were joined"

    # And every non-row section of the payload is untouched.
    skip = {"grab_now", "best_available", "bye_collisions", "sync", "data"}
    for key in set(with_byes) | set(without):
        if key in skip:
            continue
        assert with_byes.get(key) == without.get(key), f"{key} moved"


def test_no_ranking_field_is_reachable_from_the_bye_path():
    """The derivation may only read the schedule frame."""
    source = (SRC / "server" / "state.py").read_text(encoding="utf-8")
    start = source.index("def bye_consistency")
    end = source.index("def _player")
    body = source[start:end]
    for forbidden in ("vorp", "points", "survival", "value", "replacement", "consensus_rank"):
        assert forbidden not in body, f"the bye derivation references {forbidden!r}"


# --- the import guard -------------------------------------------------------------

BYE_NAMES = {"bye_weeks", "bye_consistency", "schedules_frame", "BYE_WINDOW"}


def _imports_of(path: Path) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


@pytest.mark.parametrize("package", ["value", "scoring", "providers"])
def test_the_value_path_does_not_import_the_bye_accessor(package: str) -> None:
    root = SRC / package
    if not root.is_dir():
        pytest.skip(f"no {package}/ package")
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if BYE_NAMES & _imports_of(path):
            offenders.append(str(path.relative_to(SRC)))
        text = path.read_text(encoding="utf-8")
        if "bye_weeks(" in text or "bye_consistency(" in text or "schedules_frame(" in text:
            offenders.append(f"{path.relative_to(SRC)} (textual reference)")
    assert not offenders, f"{package}/ reaches the bye accessor: {offenders}"


def test_byes_are_not_a_field_on_the_player_models() -> None:
    from audible.models.player import PlayerProjection, RawPlayerLine

    for model in (RawPlayerLine, PlayerProjection):
        fields = set(getattr(model, "__dataclass_fields__", {}))
        assert "bye" not in fields
        assert "bye_week" not in fields
    model_src = (SRC / "models" / "player.py").read_text(encoding="utf-8")
    assert "bye" not in model_src.lower()


# --- collisions -------------------------------------------------------------------

def test_two_same_position_players_on_one_bye_are_reported(service):
    service.session.picks = [
        Pick(pick_no=1, round=1, draft_slot=4, player_id="p001"),   # RB, BUF
        Pick(pick_no=2, round=1, draft_slot=4, player_id="p005"),   # RB, BUF
    ]
    out = _bye_collisions(service, {"BUF": 7})
    assert out == [{"week": 7, "position": "RB", "players": ["Player 001", "Player 005"]}]


def test_different_positions_on_one_bye_are_not_a_collision(service):
    service.session.picks = [
        Pick(pick_no=1, round=1, draft_slot=4, player_id="p001"),   # RB
        Pick(pick_no=2, round=1, draft_slot=4, player_id="p003"),   # QB (odd -> BUF)
    ]
    assert _bye_collisions(service, {"BUF": 7}) == []


def test_another_teams_picks_are_not_mine(service):
    service.session.picks = [
        Pick(pick_no=1, round=1, draft_slot=1, player_id="p001"),
        Pick(pick_no=2, round=1, draft_slot=1, player_id="p005"),
    ]
    assert _bye_collisions(service, {"BUF": 7}) == []


def test_no_byes_means_no_collisions(service):
    service.session.picks = [
        Pick(pick_no=1, round=1, draft_slot=4, player_id="p001"),
        Pick(pick_no=2, round=1, draft_slot=4, player_id="p005"),
    ]
    assert _bye_collisions(service, {}) == []


def test_the_collision_report_carries_no_judgment(service):
    """Hard stop 3: it may not know about lineup slots or starter counts."""
    service.session.picks = [
        Pick(pick_no=1, round=1, draft_slot=4, player_id="p001"),
        Pick(pick_no=2, round=1, draft_slot=4, player_id="p005"),
    ]
    row = _bye_collisions(service, {"BUF": 7})[0]
    assert set(row) == {"week", "position", "players"}
    for banned in ("severity", "score", "rank", "recommend", "starters", "slot"):
        assert banned not in row

    source = (SRC / "server" / "state.py").read_text(encoding="utf-8")
    body = source[source.index("def _bye_collisions"):source.index("def _undo")]
    for banned in ("roster_slots", "unfilled", "starters_complete", "slot_eligibility"):
        assert banned not in body, f"the collision report reaches for {banned!r}"
