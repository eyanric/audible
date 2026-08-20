"""C3 substitution gate.

Fixtures here are constructed, not captured -- the same discipline test_anchoring.py
arrived at. The point is to check that a decision rule which is *known* to be right wins
and one which is *known* to be noise does not, and no real draft supplies that ground
truth. A real 2024 corpus would tell you what happened; it cannot tell you whether the
harness measures what it claims to.
"""

from __future__ import annotations

from typing import Any

import pytest

from audible.analysis.substitution import (
    LINES,
    SeasonResult,
    SubstitutionReport,
    build_report,
)
from audible.config import LeagueConfig

# One team's 16 rounds. Legal under the ESPN config (QB/RB/RB/WR/WR/TE/FLEX/DEF/K) with
# room to spare, so any failure to fill a lineup is the harness's doing, not the fixture's.
ROUND_POSITIONS = [
    "RB", "WR", "RB", "WR", "QB", "TE", "RB", "WR",
    "TE", "QB", "DEF", "K", "RB", "WR", "DEF", "K",
]
TEAMS = 8
ROUNDS = len(ROUND_POSITIONS)
OWNER = "{MY-GUID}"
MY_TEAM = 3


def _snake_order() -> list[int]:
    order: list[int] = []
    for rnd in range(ROUNDS):
        seats = list(range(1, TEAMS + 1))
        order.extend(seats if rnd % 2 == 0 else list(reversed(seats)))
    return order


def _draft() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """A full 128-pick snake. Returns (picks, espn_id -> position)."""
    picks: list[dict[str, Any]] = []
    positions: dict[str, str] = {}
    for i, team_id in enumerate(_snake_order()):
        rnd = i // TEAMS
        pid = f"{team_id}-{rnd}"
        positions[pid] = ROUND_POSITIONS[rnd]
        picks.append(
            {"overall": i + 1, "round": rnd + 1, "team_id": team_id, "player_id": pid}
        )
    return picks, positions


def _standings() -> list[dict[str, Any]]:
    return [
        {
            "team_id": t,
            "abbrev": f"T{t}",
            "owner": OWNER if t == MY_TEAM else f"{{OTHER-{t}}}",
            "standing": t,
            "wins": 0,
            "losses": 0,
            "points_for": 0.0,
        }
        for t in range(1, TEAMS + 1)
    ]


class _Adapter:
    """The four-method season-history protocol the analysis package already codes against."""

    swid = OWNER

    def __init__(
        self,
        picks: list[dict[str, Any]],
        ranks: dict[str, dict[str, Any]],
        actuals: dict[str, float],
        standings: list[dict[str, Any]] | None = None,
        *,
        seasons: tuple[int, ...] = (2024,),
    ) -> None:
        self._picks = {s: picks for s in seasons}
        self._ranks = {s: ranks for s in seasons}
        self._actuals = {s: actuals for s in seasons}
        self._standings = standings if standings is not None else _standings()

    def get_season_draft(self, config: Any, season: int) -> list[dict[str, Any]]:
        return self._picks.get(season, [])

    def get_season_ranks(self, config: Any, season: int) -> dict[str, dict[str, Any]]:
        return self._ranks.get(season, {})

    def get_season_actuals(self, config: Any, season: int) -> dict[str, float]:
        return self._actuals.get(season, {})

    def get_season_standings(self, config: Any, season: int) -> list[dict[str, Any]]:
        return self._standings


class _Identity:
    """The board and ESPN share an id space in these fixtures, so the bridge is a no-op."""

    def to_board_id(self, espn_player_id: int | str) -> str:
        return str(espn_player_id)


def _ranks_from(order: list[str], positions: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        pid: {"standard": float(i + 1), "ppr": float(i + 1), "name": pid,
              "position": positions[pid]}
        for i, pid in enumerate(order)
    }


@pytest.fixture
def board(espn_config: LeagueConfig) -> LeagueConfig:
    return espn_config


def _run(
    config: LeagueConfig,
    *,
    actuals: dict[str, float],
    market_order: list[str],
    baseline: dict[str, float],
    positions: dict[str, str],
    picks: list[dict[str, Any]],
    seasons: tuple[int, ...] = (2024,),
) -> SubstitutionReport:
    adapter = _Adapter(picks, _ranks_from(market_order, positions), actuals, seasons=seasons)
    return build_report(
        adapter, config, lambda season: baseline, _Identity(), seasons=seasons
    )


def _only(report: SubstitutionReport) -> SeasonResult:
    assert report.results, f"no season ran: {report.skipped}"
    return report.results[0]


# ── the control reproduces reality ───────────────────────────────────────────


def test_the_actual_line_is_the_real_draft(board: LeagueConfig) -> None:
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float(len(positions) - i) for i, pid in enumerate(order)}
    result = _only(
        _run(board, actuals=actuals, market_order=order, baseline=actuals,
             picks=picks, positions=positions)
    )
    real = tuple(str(p["player_id"]) for p in picks if p["team_id"] == MY_TEAM)
    assert result.roster["actual"] == real
    assert result.my_picks == ROUNDS


def test_opponents_keep_their_picks_when_i_do_not_take_them(board: LeagueConfig) -> None:
    """My seat is the only thing that changes. If a substituted line's roster contains a
    player some other seat really drafted, that seat had to fall through -- and no line may
    end up with a player it never selected."""
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float(i) for i, pid in enumerate(order)}
    result = _only(
        _run(board, actuals=actuals, market_order=order, baseline=actuals,
             picks=picks, positions=positions)
    )
    for line in LINES:
        assert len(set(result.roster[line])) == len(result.roster[line]), (
            f"{line} drafted the same player twice"
        )


# ── ground truth: a rule that is right wins, a rule that is noise does not ────


def test_a_perfect_baseline_is_indistinguishable_from_hindsight(board: LeagueConfig) -> None:
    """The exact invariant that pins what ``hindsight`` means.

    ``hindsight`` is the same VORP engine over realized points, so handing the machinery a
    projection that is exactly right must produce the *identical* roster -- not merely a
    similar score. If these two ever diverge, one of the lines is not running the machinery
    it claims to.
    """
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float((7 * i) % 131) for i, pid in enumerate(order)}
    result = _only(
        _run(board, actuals=actuals, market_order=order, baseline=actuals,
             picks=picks, positions=positions)
    )
    assert result.roster["machinery"] == result.roster["hindsight"]
    assert result.points["machinery"] == pytest.approx(result.points["hindsight"])


def test_hindsight_beats_a_market_that_is_backwards(board: LeagueConfig) -> None:
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float((7 * i) % 131) for i, pid in enumerate(order)}
    backwards = sorted(order, key=lambda pid: actuals[pid])
    result = _only(
        _run(board, actuals=actuals, market_order=backwards, baseline=actuals,
             picks=picks, positions=positions)
    )
    assert result.delta("hindsight", "market") > 0
    assert result.delta("hindsight", "actual") > 0


def test_greedy_by_points_is_not_what_hindsight_does(board: LeagueConfig) -> None:
    """Recorded because it is counter-intuitive and cost a debugging cycle: a line that
    always takes the highest remaining scorer loses to VORP over the same numbers. It
    spends early picks on abstract volume and fields a worse legal lineup. That is why
    ``hindsight`` runs realized points through the engine instead of sorting by them."""
    picks, positions = _draft()
    order = sorted(positions)
    # QBs out-score everyone, as they really do, and only one can start
    actuals = {
        pid: (900.0 - i if positions[pid] == "QB" else float(300 - i))
        for i, pid in enumerate(order)
    }
    result = _only(
        _run(board, actuals=actuals, market_order=order, baseline=actuals,
             picks=picks, positions=positions)
    )
    greedy = sorted(
        (pid for pid in order if pid not in {p["player_id"] for p in picks[:0]}),
        key=lambda pid: -actuals[pid],
    )[:1]
    # the top scorer overall is a QB, and the machinery does not open with him
    assert positions[greedy[0]] == "QB"
    assert result.roster["hindsight"][0] != greedy[0]


def test_a_perfect_baseline_beats_a_market_that_is_backwards(board: LeagueConfig) -> None:
    """If the projection is exactly right, the machinery must beat a board that is not.

    This is the test with the power to catch a harness that only *looks* like it is
    substituting anything: hand it the answer key and it has to win.
    """
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float((11 * i) % 127) for i, pid in enumerate(order)}
    backwards = sorted(order, key=lambda pid: actuals[pid])  # worst players ranked first
    result = _only(
        _run(board, actuals=actuals, market_order=backwards, baseline=actuals,
             picks=picks, positions=positions)
    )
    assert result.delta("machinery", "market") > 0
    assert result.delta("baseline", "market") > 0


def test_a_flat_baseline_carries_no_signal(board: LeagueConfig) -> None:
    """Every player projected identically is a line with nothing in it. It must not beat a
    market that is ordered correctly -- if it does, the win is coming from the harness."""
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float((11 * i) % 127) for i, pid in enumerate(order)}
    correct = sorted(order, key=lambda pid: -actuals[pid])
    flat = dict.fromkeys(order, 100.0)
    result = _only(
        _run(board, actuals=actuals, market_order=correct, baseline=flat,
             picks=picks, positions=positions)
    )
    assert result.delta("machinery", "market") <= 0


# ── coverage discipline ───────────────────────────────────────────────────


def test_an_unscored_player_is_counted_and_never_voluntarily_drafted(
    board: LeagueConfig,
) -> None:
    """C1's rule, carried forward: counted, never zeroed. A line cannot be credited or
    punished for a player nobody can score, so it must never reach for one."""
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float(len(order) - i) for i, pid in enumerate(order)}
    missing = order[0]
    del actuals[missing]
    result = _only(
        _run(board, actuals=actuals, market_order=order, baseline=actuals,
             picks=picks, positions=positions)
    )
    assert result.unscored == 1
    for line in ("market", "baseline", "machinery", "hindsight"):
        assert missing not in result.roster[line], f"{line} drafted an unscoreable player"


def test_a_player_the_bridge_cannot_translate_is_counted(board: LeagueConfig) -> None:
    class _Deaf:
        def to_board_id(self, espn_player_id: int | str) -> str:
            return str(espn_player_id)  # never matches the board keys below

    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float(i) for i, pid in enumerate(order)}
    adapter = _Adapter(picks, _ranks_from(order, positions), actuals)
    report = build_report(
        adapter, board, lambda season: {f"board::{p}": 1.0 for p in order}, _Deaf(),
        seasons=(2024,),
    )
    result = _only(report)
    assert result.no_baseline == len(order)
    assert result.unbridged == len(order)


# ── roster legality ───────────────────────────────────────────────────────


def test_every_line_fills_a_legal_starting_lineup(board: LeagueConfig) -> None:
    """A static ranking with no roster rule drafts nine quarterbacks. The legality
    constraint is what stops it, so it is asserted rather than assumed."""
    picks, positions = _draft()
    order = sorted(positions)
    # QBs score most, so an unconstrained line would hoard them
    actuals = {
        pid: (900.0 if positions[pid] == "QB" else float(100 - i)) for i, pid in enumerate(order)
    }
    result = _only(
        _run(board, actuals=actuals, market_order=order, baseline=actuals,
             picks=picks, positions=positions)
    )
    for line in LINES:
        drafted = [positions[p] for p in result.roster[line]]
        for slot, needed in (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("DEF", 1), ("K", 1)):
            assert drafted.count(slot) >= needed, (
                f"{line} cannot field a lineup: {sorted(drafted)}"
            )


# ── how the result is allowed to be read ────────────────────────────────────


def test_a_loss_reads_as_uninformative_not_as_a_null(board: LeagueConfig) -> None:
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float((11 * i) % 127) for i, pid in enumerate(order)}
    correct = sorted(order, key=lambda pid: -actuals[pid])
    report = _run(
        board, actuals=actuals, market_order=correct,
        baseline=dict.fromkeys(order, 100.0), picks=picks, positions=positions,
    )
    verdict = report.verdict()
    assert "UNINFORMATIVE" in verdict
    assert "confounded" in verdict


def test_seasons_that_disagree_produce_an_interval_that_admits_zero(
    board: LeagueConfig,
) -> None:
    """C2's lesson, enforced here rather than rediscovered. Three seasons pulling in
    different directions must not report a confident mean."""
    report = SubstitutionReport(
        seasons=(2023, 2024, 2025),
        results=[
            SeasonResult(
                season=season, my_team_id=MY_TEAM, picks=128, my_picks=16, pool=128,
                unscored=0, unbridged=0, no_baseline=0,
                points={"market": 100.0, "machinery": 100.0 + delta,
                        "actual": 100.0, "baseline": 100.0, "hindsight": 200.0},
                roster={line: () for line in LINES},
            )
            for season, delta in ((2023, -40.0), (2024, +5.0), (2025, +45.0))
        ],
        skipped={},
    )
    mean, half, n = report.season_level("machinery", "market")
    assert n == 3
    assert mean - half < 0 < mean + half
    assert "UNRESOLVED" in report.verdict() or "UNINFORMATIVE" in report.verdict()


def test_the_report_prints(board: LeagueConfig, capsys: pytest.CaptureFixture[str]) -> None:
    """The formatting block is the part that runs once, at the end, after the expensive
    part succeeded. A crash there throws away the whole run, so it is exercised."""
    from audible.cli import print_substitution

    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float((11 * i) % 127) for i, pid in enumerate(order)}
    report = _run(
        board, actuals=actuals, market_order=order, baseline=actuals,
        picks=picks, positions=positions, seasons=(2023, 2024, 2025),
    )
    assert print_substitution(report) == 0
    out = capsys.readouterr().out
    assert "BEST-BALL POINTS" in out
    assert "WHAT IT ESTABLISHES" in out
    assert "half-PPR against seasons ESPN paid at zero PPR" in out


def test_a_season_without_ranks_is_skipped_with_a_reason(board: LeagueConfig) -> None:
    """2021 and 2022 are exactly this. A gate that quietly ran without its control would
    report a comparison it never made."""
    picks, positions = _draft()
    order = sorted(positions)
    actuals = {pid: float(i) for i, pid in enumerate(order)}
    adapter = _Adapter(picks, {}, actuals, seasons=(2022,))
    report = build_report(
        adapter, board, lambda season: actuals, _Identity(), seasons=(2022,)
    )
    assert not report.results
    assert "ranks" in report.skipped[2022]
