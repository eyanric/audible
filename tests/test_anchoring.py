"""B1 opponent anchoring -- synthetic drafts with a known answer.

Fixtures here are constructed, not captured: the point is to check that a manager who
demonstrably drafts off one board is classified as reading that board, which needs a ground
truth no real draft supplies.
"""

from __future__ import annotations

from typing import Any

from audible.analysis.anchoring import (
    DIVERGENCE_MIN,
    MIN_DIVERGENT,
    RANK_HORIZON,
    build_report,
    seat_verdict,
    sign_test,
)


def _board(n: int = 60, *, divergent_every: int = 3, swing: float = 40.0) -> dict[str, Any]:
    """A board where every `divergent_every`-th player is a 'Henry type'.

    Those sit far higher on STANDARD than on PPR, which is the only place the two orderings
    carry information about which one a manager is reading.
    """
    ranks: dict[str, Any] = {}
    for i in range(1, n + 1):
        standard = float(i)
        ppr = float(i + swing) if i % divergent_every == 0 else float(i)
        ranks[str(i)] = {"standard": standard, "ppr": ppr, "name": f"P{i}", "position": "RB"}
    return ranks


def _draft_by(ranks: dict[str, Any], key: str, team_id: int, n: int = 30) -> list[dict[str, Any]]:
    """One manager drafting exactly off the `key` board: each player taken AT his rank on it.

    Taking them in `key` *order* is not the same thing and does not express the ground truth
    -- the two boards have gaps and collisions relative to each other, so sequential pick
    numbers drift away from the rank they are supposed to match, and the deviation the metric
    measures flips sign partway down the board.
    """
    order = sorted(ranks, key=lambda pid: ranks[pid][key])[:n]
    return [
        {
            "overall": int(ranks[pid][key]),
            "round": 1,
            "team_id": team_id,
            "player_id": pid,
        }
        for pid in order
    ]


# --- the classifier ------------------------------------------------------------------------


def test_a_manager_drafting_espns_board_is_read_as_espn() -> None:
    ranks = _board()
    picks = _draft_by(ranks, "standard", team_id=1)
    verdict = seat_verdict(1, "AAA", {2024: (picks, ranks)})

    assert verdict.label == "espn"
    assert verdict.edge > 0
    assert verdict.divergent >= MIN_DIVERGENT


def test_a_manager_drafting_a_ppr_board_is_read_as_ppr() -> None:
    """The exploitable seat: someone on a PPR board in a league paying RBs 0.0/reception.

    Takes the whole board, not a slice: the divergent players sit 40 ranks DOWN a PPR board,
    so a truncated draft reaches none of them and there is nothing to classify on.
    """
    ranks = _board()
    picks = _draft_by(ranks, "ppr", team_id=2, n=60)
    verdict = seat_verdict(2, "BBB", {2024: (picks, ranks)})

    assert verdict.divergent >= MIN_DIVERGENT
    assert verdict.label == "ppr"
    assert verdict.edge < 0
    assert verdict.exploitable is True


def test_too_few_discriminating_picks_stays_unclassified() -> None:
    """A direction read off three players is not a finding."""
    ranks = _board(divergent_every=25)  # almost nothing separates the boards
    picks = _draft_by(ranks, "standard", team_id=3)
    verdict = seat_verdict(3, "CCC", {2024: (picks, ranks)})

    assert verdict.divergent < MIN_DIVERGENT
    assert verdict.label == "unclassified"


def test_a_manager_who_leans_both_ways_stays_unclassified() -> None:
    """Drafting neither board consistently must not be forced into one.

    A divergent player taken EARLIER than both ranks reads as STANDARD-anchored (+swing);
    taken LATER than both, it reads as PPR-anchored (-swing). Alternating the two produces a
    manager with no consistent lean, which is what the interval has to catch.
    """
    ranks = _board(n=60)
    divergent = [pid for pid in ranks if abs(ranks[pid]["standard"] - ranks[pid]["ppr"]) >= 10]
    picks: list[dict[str, Any]] = []
    for i, pid in enumerate(sorted(divergent, key=int)):
        # alternate: reach for him at pick 2, then let him slide to pick 190
        overall = 2 if i % 2 == 0 else 190
        picks.append({"overall": overall, "round": 1, "team_id": 4, "player_id": pid})

    verdict = seat_verdict(4, "DDD", {2024: (picks, ranks)})
    assert verdict.divergent >= MIN_DIVERGENT
    assert verdict.label == "unclassified"


# --- the horizon: the bug this found --------------------------------------------------------


def test_the_degenerate_rank_tail_is_excluded() -> None:
    """ESPN ranks only the top of its board and fills the rest with placeholders running to
    2687. A player at STANDARD 57 and PPR 2554 is not the boards disagreeing about him -- it
    is one board declining to rank him, and left in, a handful of these dominated every
    average (mean divergence 85.2 against a median of 10.0).
    """
    ranks = _board(n=20)
    ranks["999"] = {"standard": 57.0, "ppr": 2554.0, "name": "Placeholder", "position": "WR"}
    picks = _draft_by(ranks, "standard", team_id=5, n=20)
    picks.append({"overall": 21, "round": 2, "team_id": 5, "player_id": "999"})

    verdict = seat_verdict(5, "EEE", {2024: (picks, ranks)})
    assert verdict.ranked_picks == 20, "the placeholder pick must not reach the statistics"
    assert abs(verdict.edge) < 100, "and must not dominate the average"


def test_the_horizon_is_inside_the_drafted_range() -> None:
    """128 picks are made; a horizon below that would discard real decisions."""
    assert RANK_HORIZON >= 128


# --- the room-level test ---------------------------------------------------------------------


def test_sign_test_reads_a_unanimous_room() -> None:
    positive, n, p = sign_test([5.0, 12.0, 3.0, 8.0, 1.0, 20.0, 6.0])
    assert (positive, n) == (7, 7)
    assert p < 0.02, "seven of seven leaning the same way is not a coin"


def test_sign_test_is_agnostic_about_a_split_room() -> None:
    positive, n, p = sign_test([5.0, -12.0, 3.0, -8.0])
    assert (positive, n) == (2, 4)
    assert p == 1.0


def test_sign_test_ignores_exact_zeros() -> None:
    assert sign_test([0.0, 0.0])[1] == 0
    assert sign_test([0.0, 4.0, 9.0])[1] == 2


# --- the report ------------------------------------------------------------------------------


class _Adapter:
    """Serves two seasons; one of them has no ranks at all, like 2021-22."""

    def __init__(self, ranks: dict[str, Any], picks: list[dict[str, Any]]) -> None:
        self._ranks, self._picks = ranks, picks

    def get_season_draft(self, _config: Any, season: int) -> list[dict[str, Any]]:
        return self._picks

    def get_season_ranks(self, _config: Any, season: int) -> dict[str, Any]:
        return {} if season == 2022 else self._ranks

    def get_season_teams(self, _config: Any, season: int) -> dict[int, str]:
        return {1: "AAA", 8: "ME"}


def test_a_season_with_no_ranks_is_excluded_not_compared_against_nothing() -> None:
    """2021 and 2022 serve 400 players and zero ranks, and sorting by an absent rank type
    returns arbitrary order with no error. Including such a season would compare every pick
    against nothing."""
    ranks = _board()
    picks = _draft_by(ranks, "standard", team_id=1)
    report = build_report(_Adapter(ranks, picks), None, seasons=(2022, 2024), me=8)

    assert report.seasons == (2024,)
    assert report.excluded_seasons == (2022,)


def test_my_own_seat_is_excluded_from_the_table() -> None:
    ranks = _board()
    picks = _draft_by(ranks, "standard", team_id=1) + [
        {"overall": 99, "round": 4, "team_id": 8, "player_id": "1"}
    ]
    report = build_report(_Adapter(ranks, picks), None, seasons=(2024,), me=8)
    assert [s.team_id for s in report.seats] == [1]


def test_coverage_counts_picks_the_board_could_not_price() -> None:
    ranks = _board(n=20)
    picks = _draft_by(ranks, "standard", team_id=1, n=20)
    picks.append({"overall": 21, "round": 2, "team_id": 1, "player_id": "no-such-player"})

    report = build_report(_Adapter(ranks, picks), None, seasons=(2024,), me=8)
    assert report.unranked_picks == 1
    assert report.total_picks == 21
    assert 0.9 < report.coverage < 1.0


def test_divergence_threshold_is_what_makes_a_pick_informative() -> None:
    """Below the threshold both boards fit equally well by construction, so those picks
    carry no information about which one was being read."""
    ranks = _board(swing=DIVERGENCE_MIN - 1)  # boards nearly agree everywhere
    picks = _draft_by(ranks, "standard", team_id=1)
    assert seat_verdict(1, "AAA", {2024: (picks, ranks)}).divergent == 0
