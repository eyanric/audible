"""S7 gates for the ADJUDICATION -- the half of this session nothing tested.

The adversarial review's finding 13: `sim/test_g_s7.py` imports `rank, room, s7_weekly` and
nothing else, so all 36 of its gates exercise phase 1's harness and NONE of them touch
`s7_phase2.loso`, `reference_p`, the floor, the verdict logic, `s7_metrics`, `s7_phase3`,
`s7_phase4.survivors` or `composite_points`. The mutation sweep inherited the same blind spot.
Those are the functions that decided every disposition this session published, and the review
found three defects in the verdict logic alone that a single gate would have caught.

EVERY GATE HERE RUNS ON SYNTHETIC INPUT WHERE THE RIGHT ANSWER IS KNOWN BY CONSTRUCTION. None of
them needs the corpus, so they run on a bare clone, and none of them can be satisfied by the code
under test agreeing with itself.
"""

from __future__ import annotations

import pytest

from . import s7_phase2 as p2
from . import s7_phase4 as p4

SCOPES_PER_SEASON = 17
SEASONS = (2019, 2020, 2021, 2022, 2023)


def _series(per_season: dict[int, dict[float, float]], base_value: float = 10.0) -> p2.Series:
    """A synthetic Series: every scope in a season scores the same under each lambda."""
    series = p2.Series()
    for lam in p2.GRID:
        series.treated[lam] = {}
    for season, by_lam in per_season.items():
        for week in range(1, SCOPES_PER_SEASON + 1):
            scope = (season, week)
            series.base[scope] = base_value
            for lam in p2.GRID:
                series.treated[lam][scope] = by_lam.get(lam, base_value)
    return series


# --- leave-one-season-out selection ---------------------------------------------------------


def test_loso_selects_zero_when_no_strength_helps() -> None:
    """The property the whole design rests on: a useless term contributes exactly 0.000.

    Without 0.0 in the grid every reported effect is forced to be an intervention, which is the
    defect that made the first phase-2 design resolve terms that damaged the board.
    """
    worse = {lam: (10.0 if lam == 0.0 else 11.0) for lam in p2.GRID}
    series = _series(dict.fromkeys(SEASONS, worse))
    selected, effects, chosen = p2.loso(series.base, series.treated)
    assert selected == 0.0, selected
    assert set(chosen.values()) == {0.0}
    assert all(value == 0.0 for value in effects.values())


def test_loso_picks_the_strength_that_helps_and_reports_the_gain() -> None:
    better = {lam: (10.0 if lam == 0.0 else 9.0) for lam in p2.GRID}
    series = _series(dict.fromkeys(SEASONS, better))
    selected, _effects, chosen = p2.loso(series.base, series.treated)
    assert selected == pytest.approx(1.0)
    assert 0.0 not in set(chosen.values())


def test_loso_never_lets_a_season_choose_its_own_strength() -> None:
    """THE WHOLE POINT OF THE PROCEDURE, and it is measured rather than asserted.

    2023 is rigged so that lambda 0.20 is a catastrophe there and a small win everywhere else.
    An in-sample selection would pick 0.20 for 2023 and be punished; an out-of-sample one picks
    it BECAUSE the other seasons liked it, which is exactly what leaks nothing.
    """
    good = {lam: (10.0 if lam == 0.0 else 9.5) for lam in p2.GRID}
    good[0.20] = 9.0
    trap = {lam: (10.0 if lam == 0.0 else 9.5) for lam in p2.GRID}
    trap[0.20] = 99.0
    per_season = dict.fromkeys(SEASONS[:-1], good)
    per_season = {**per_season, 2023: trap}
    _selected, effects, chosen = p2.loso(_series(per_season).base, _series(per_season).treated)
    assert chosen[2023] == 0.20, chosen
    held = [value for scope, value in effects.items() if scope[0] == 2023]
    assert held and all(value == pytest.approx(10.0 - 99.0) for value in held)


def test_loso_with_one_season_cannot_select_and_says_so() -> None:
    """No other season to fit on, so the fallback is 0.0 -- never the season's own best."""
    per_season = {2019: {lam: (10.0 if lam == 0.0 else 1.0) for lam in p2.GRID}}
    series = _series(per_season)
    selected, _effects, chosen = p2.loso(series.base, series.treated)
    assert chosen == {2019: 0.0}
    assert selected == 0.0


# --- the reference-set p, its mirror, and its reachable range -------------------------------


def test_reference_p_is_smallest_when_the_term_beats_every_draw() -> None:
    floor = [float(-i) for i in range(1, 41)]
    assert p2.reference_p(100.0, floor) == pytest.approx(1 / 41)
    assert p2.reference_p(-100.0, floor) == pytest.approx(41 / 41)


def test_harm_p_is_the_mirror_and_the_first_version_had_it_backwards() -> None:
    """A harm reads p near 1.0 on `reference_p`; the HARM branch used to look for p <= 0.05."""
    floor = [float(-i) for i in range(1, 41)]
    assert p2.reference_p(-100.0, floor) == pytest.approx(1.0)
    assert p2.harm_p(-100.0, floor) == pytest.approx(1 / 41)
    assert p2.harm_p(100.0, floor) == pytest.approx(1.0)


def test_null_hit_rate_is_two_in_fortyone_only_when_there_are_no_ties() -> None:
    distinct = [float(i) for i in range(40)]
    assert p2.null_hit_rate(100.0, distinct) == pytest.approx(2 / 41)


def test_null_hit_rate_is_zero_when_the_floor_ties_at_the_maximum() -> None:
    """THE FINDING THAT BROKE THE FIRST MULTIPLICITY BENCHMARK.

    With three or more of the 41 values tied at the top, every one of them sees at least two
    others at least as large, so the smallest reachable p is 3/41 = 0.073 and the test cannot
    return a hit at 0.05 however real the effect. A flat 2/41 benchmark counts those tests as
    though they could.
    """
    tied = [0.0] * 39 + [-1.0]
    assert p2.null_hit_rate(0.0, tied) == 0.0
    assert p2.achievable_p(0.0, tied) > 0.05


def test_null_hit_rate_and_achievable_p_agree_about_whether_a_hit_is_possible() -> None:
    for floor, observed in (
        ([float(i) for i in range(40)], 100.0),
        ([0.0] * 39 + [-1.0], 0.0),
        ([0.0] * 20 + [float(-i) for i in range(1, 21)], 0.0),
        ([0.0] * 39 + [-1.0], 5.0),
    ):
        reachable = p2.achievable_p(observed, floor) <= 0.05
        assert (p2.null_hit_rate(observed, floor) > 0.0) == reachable, (observed, floor[:3])


# --- the floor is a permutation of the term's own values ------------------------------------


def test_the_floor_preserves_the_terms_own_marginal_distribution() -> None:
    """The property that makes the salt exchangeable with the signal, which a hash is not."""
    values = {f"p{i:03d}": float(i % 5) for i in range(50)}
    covered = list(values)
    position = dict.fromkeys(covered, "WR")
    drawn = p2.floor_values(values, covered, position, set(), 2024, 7)
    assert sorted(drawn.values()) == sorted(values.values())
    assert set(drawn) == set(values)


def test_the_floor_actually_moves_the_values_to_other_players() -> None:
    values = {f"p{i:03d}": float(i) for i in range(50)}
    covered = list(values)
    position = dict.fromkeys(covered, "WR")
    drawn = p2.floor_values(values, covered, position, set(), 2024, 7)
    assert sum(1 for pid in covered if drawn[pid] != values[pid]) > 40


def test_the_floor_is_deterministic_in_its_salt_and_differs_between_salts() -> None:
    values = {f"p{i:03d}": float(i) for i in range(50)}
    covered = list(values)
    position = dict.fromkeys(covered, "WR")
    first = p2.floor_values(values, covered, position, set(), 2024, 1)
    again = p2.floor_values(values, covered, position, set(), 2024, 1)
    other = p2.floor_values(values, covered, position, set(), 2024, 2)
    assert first == again
    assert first != other


def test_a_position_level_constant_is_permuted_ACROSS_positions() -> None:
    """`availability` is four rates. Dealing them to individual players would manufacture
    within-position spread the term provably cannot have, and the floor would then be a
    different kind of object from the treatment."""
    position = {}
    values = {}
    rates = {"QB": 1.0, "RB": 2.0, "WR": 3.0, "TE": 4.0}
    for index, (pos, rate) in enumerate(rates.items()):
        for i in range(12):
            pid = f"{pos}{i:02d}"
            position[pid] = pos
            values[pid] = rate
        assert index >= 0
    covered = list(values)
    drawn = p2.floor_values(values, covered, position, set(rates), 2024, 3)
    by_position = {pos: {drawn[pid] for pid in covered if position[pid] == pos} for pos in rates}
    for pos, held in by_position.items():
        assert len(held) == 1, (pos, held)
    assert sorted(next(iter(v)) for v in by_position.values()) == sorted(rates.values())


# --- the verdict --------------------------------------------------------------------------


def _record(p_position: dict[str, float], harm: dict[str, float] | None = None) -> dict:
    return {"p_position": p_position, "harm_p_position": harm or {}}


def test_a_harm_can_never_be_certified_material_by_its_own_magnitude() -> None:
    """THE DEFECT THAT PUT `ngs_separation` IN A COMPOSITE. It scored -0.1404 board-wide at
    p 0.9268 -- it lost to 38 of 40 floor draws -- and the old `max(abs(...))` read it as
    material."""
    record = _record({"WR": 0.0244})
    out = p2.verdict_of(
        record, locus=("WR",), selected=-0.1404, pos_selected={"WR": 0.0411},
        p_board=0.9268, p_board_harm=0.5, frozen=set(),
    )
    assert out["verdict"] == "resolves but immaterial", out
    assert out["material"] is False


def test_a_real_board_level_gain_still_resolves() -> None:
    out = p2.verdict_of(
        _record({}), locus=(), selected=0.25, pos_selected={}, p_board=0.0244,
        p_board_harm=1.0, frozen=set(),
    )
    assert out["verdict"] == "RESOLVES"
    assert out["material"] is True


def test_an_off_locus_hit_is_a_lead_and_never_a_resolution() -> None:
    """`inj_status` at WR: +0.1919 at p 0.0244, off a board-level pre-registration. Moving the
    locus afterwards is how a null becomes a headline, so it stays OFF-LOCUS -- but it is
    material, which the first version denied because it only looked inside the locus."""
    out = p2.verdict_of(
        _record({"WR": 0.0244}), locus=(), selected=-0.0107, pos_selected={"WR": 0.1919},
        p_board=0.4146, p_board_harm=0.6, frozen=set(),
    )
    assert out["verdict"] == "OFF-LOCUS"
    assert out["off_locus"] == ["WR"]
    assert out["off_locus_material"] is True


def test_a_material_harm_is_reported_as_a_harm() -> None:
    """The branch fired ZERO times in 72 measurements because it tested the p backwards."""
    out = p2.verdict_of(
        _record({"WR": 0.9}, harm={"WR": 0.0244}), locus=("WR",), selected=-0.30,
        pos_selected={"WR": -0.30}, p_board=0.95, p_board_harm=0.0244, frozen=set(),
    )
    assert out["verdict"] == "HARM"
    assert "WR" in out["harms"] and "board" in out["harms"]


def test_a_structurally_frozen_position_cannot_produce_an_off_locus_hit() -> None:
    out = p2.verdict_of(
        _record({"WR": 0.0244}), locus=(), selected=0.0, pos_selected={"WR": 0.5},
        p_board=0.5, p_board_harm=0.5, frozen={"WR"},
    )
    assert out["off_locus"] == []
    assert out["verdict"] == "null"


# --- phase 4 ---------------------------------------------------------------------------------


def test_only_a_RESOLVES_record_becomes_a_survivor(tmp_path, monkeypatch) -> None:
    import json

    runs = tmp_path / "runs"
    runs.mkdir()
    rows = [
        {"signal": "a", "verdict": "RESOLVES", "chosen": {"2019": 0.05, "2020": 0.05},
         "effect_board": 0.2, "p_board": 0.0244, "locus_hits": ["WR"]},
        {"signal": "b", "verdict": "resolves but immaterial", "chosen": {"2019": 0.05}},
        {"signal": "c", "verdict": "OFF-LOCUS", "chosen": {"2019": 0.05}},
        {"signal": "d", "verdict": "RESOLVES", "chosen": {"2019": 0.0, "2020": 0.0}},
    ]
    (runs / "s7-phase2-lg.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    (runs / "s7-phase3-lg.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(p4, "RUNS", runs)
    terms, excluded = p4.survivors("lg")
    assert [term.name for term in terms] == ["a"]
    assert any("every selected lambda was 0.0" in line for line in excluded)
    assert len(excluded) == 3
    assert terms[0].where == "WR"


def test_survivors_refuses_to_invent_a_missing_phase(tmp_path, monkeypatch) -> None:
    from . import rank

    monkeypatch.setattr(p4, "RUNS", tmp_path)
    with pytest.raises(rank.PreflightError, match="phase"):
        p4.survivors("lg")


def test_the_modal_lambda_is_a_grid_point_and_never_an_average(tmp_path, monkeypatch) -> None:
    """Averaging two grid points produces a strength no fold ever chose."""
    import json

    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "s7-phase2-lg.jsonl").write_text(
        json.dumps({
            "signal": "a", "verdict": "RESOLVES",
            "chosen": {"2019": 0.02, "2020": 0.20, "2021": 0.20},
            "effect_board": 0.2, "p_board": 0.02,
        }), encoding="utf-8",
    )
    (runs / "s7-phase3-lg.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(p4, "RUNS", runs)
    terms, _excluded = p4.survivors("lg")
    assert terms[0].lam == 0.20
    assert terms[0].lam in p2.GRID


def test_an_in_season_term_is_never_draft_capable() -> None:
    weekly = p4.Term("inj_status", 0.05, "phase3", 0.1, 0.02, "board", "WR")
    seasonal = p4.Term("snap_share", 0.05, "phase2", 0.1, 0.02, "position", "board")
    assert weekly.draft_capable is False
    assert seasonal.draft_capable is True
