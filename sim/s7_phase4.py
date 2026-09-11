"""S7 phase 4 -- assemble the board, and confirm it where it ships.

    uv run python -m sim.s7_phase4 espn_green_hope  >> sim/runs/s7-phase4.txt

WHAT IT COMBINES. Everything phases 2 and 3 left standing, read from their committed
`s7-phase2-<league>.jsonl` and `s7-phase3-<league>.jsonl` rather than retyped, so the composite
cannot contain a term the adjudication did not pass. A record counts as a survivor only if its
verdict is `RESOLVES` -- which already requires a reference-set p at or under 0.05, the right sign
at a pre-registered locus, AND an effect of at least `MATERIAL` RWRE. `resolves but immaterial` is
listed and excluded.

THE MODEL IS ONE FUNCTION AND ITS INPUTS ARE NOT ALL AVAILABLE AT THE DRAFT. That is the honest
reading of "one ranking system, used at the draft and in-season", and it splits the survivors in
two:

  DRAFT TERMS are seasonal priors -- last year's snap share, draft capital, a contract. They exist
  in August, so they go in the preseason board and can be confirmed against the incumbent.

  IN-SEASON TERMS read a column that only exists once a week has a number: an injury designation,
  a week-over-week role change, this week's projected dispersion. There is no preseason value for
  them, so they cannot enter a draft board at all. Reporting a weekly gain from those as though it
  were a draft-board gain would be the central error this phase exists to avoid.

Both sets are reported. The transfer question -- do weekly gains show up at the draft -- is asked
only of the DRAFT terms, because it is only meaningful for them.

THE INCUMBENT BAR IS THE ESPN ARM AND THE BOARD UNDER TEST IS THE FFA ARM, so three numbers are
always printed together: the incumbent (22.43 / 28.10 / 32.63, symmetric indexing, from
`sim/runs/s6-bar.out`), the untreated FFA board, and the treated FFA board. Comparing a treated
FFA board against an ESPN incumbent without the untreated FFA board in between would attribute
the arm difference to the treatment.

AND THE TWO ARMS DO NOT COVER THE SAME SEASONS. `rank.SEASONS_BY_ARM` excludes espn 2023 -- 129 of
1,128 non-zero, S1's finding -- so the incumbent mean is over six seasons and FFA has seven. Every
seasonal figure is therefore reported twice: over FFA's own seven, and over the six the incumbent
actually used. A seven-season mean compared with a six-season mean is not a comparison.

ONE EXTRA PARAMETER, AND ONLY ONE. Each surviving term enters at the lambda its own
leave-one-season-out selection chose. Terms overlap -- snap share and route participation are both
volume -- so a composite of individually-tuned terms can overshoot, and a single global gain `g`
scales the whole adjustment. `g` is selected out of sample like everything else, and the grid
includes 0.0 and 1.0, so the composite can decline to exist and can decline to be scaled.
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import arms, rank, signals
from . import s7_metrics as metrics
from . import s7_phase2 as p2
from . import s7_phase3 as p3
from . import s7_weekly as s7

RUNS = Path(__file__).resolve().parent / "runs"

# From `sim/runs/s6-bar.out`: the ESPN arm through the current transform, symmetric indexing,
# averaged over the six seasons that arm covers. Quoted in the handoff and NOT recomputed here --
# `sim/runs/s6_bar.py` is the committed script that produced them.
INCUMBENT: dict[str, float] = {
    "espn_green_hope": 22.43, "espn_danger_zone": 28.10, "sleeper_boyfun": 32.63,
}

# The global gain. 0.0 means "no composite"; 1.0 means "every term at its own selected strength".
GAIN_GRID: tuple[float, ...] = (0.0, 0.25, 0.50, 0.75, 1.00, 1.25)

# Walk-forward. Identical to `rank.FIT_SEASONS` / `rank.TEST_SEASONS` so this phase cannot quietly
# pick a friendlier split than the rest of the project uses.
FIT = rank.FIT_SEASONS
TEST = rank.TEST_SEASONS


@dataclass(frozen=True, slots=True)
class Term:
    """A survivor, with the strength its own adjudication chose."""

    name: str
    lam: float
    source: str  # "phase2" (a seasonal prior) or "phase3" (a weekly column)
    effect: float
    p_value: float
    scope: str

    @property
    def draft_capable(self) -> bool:
        """A phase-3 metric reads a per-week column and has no preseason value."""
        return self.source == "phase2"


def _records(phase: str, league: str) -> list[dict[str, Any]]:
    path = RUNS / f"s7-{phase}-{league}.jsonl"
    if not path.exists():
        raise rank.PreflightError(
            f"{path} is missing. Phase 4 combines what phases 2 and 3 committed and does not "
            "re-derive it; run that phase first."
        )
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def survivors(league: str) -> tuple[list[Term], list[str]]:
    """Every RESOLVES record, plus the names of everything excluded and why."""
    terms: list[Term] = []
    excluded: list[str] = []
    for phase in ("phase2", "phase3"):
        for record in _records(phase, league):
            name = record.get("signal") or record.get("metric")
            verdict = record.get("verdict", "null")
            if verdict != "RESOLVES":
                excluded.append(f"{name}: {verdict}")
                continue
            chosen = record.get("chosen") or {}
            lams = [value for value in chosen.values() if value]
            if not lams:
                excluded.append(f"{name}: RESOLVES but every selected lambda was 0.0")
                continue
            # The MODAL selected lambda, not the mean: the grid is discrete and averaging two
            # grid points produces a strength no fold ever chose.
            lam = max(set(lams), key=lams.count)
            if name == "floor_ceiling_tilt":
                excluded.append(f"{name}: a board construction, handled separately")
                continue
            scope = (
                p3.SCOPE.get(name, "position") if phase == "phase3"
                else signals.SIGNAL_SCOPE.get(name, "position")
            )
            terms.append(Term(
                name=name, lam=float(lam), source=phase,
                effect=float(record.get("effect_board") or 0.0),
                p_value=float(record.get("p_board") or 1.0), scope=scope,
            ))
    return terms, excluded


def _values(term: Term, board: Any, season: int, week: int, league: str) -> dict[str, float]:
    if term.source == "phase3":
        return metrics.METRICS[term.name](board, season, week, league)
    signal = next(s for s in p2.SIGNALS if s.name == term.name)
    return p2.values_for(signal, board, season, league)


def _kwargs(term: Term) -> dict[str, Any]:
    if term.source == "phase3":
        return {"scope": term.scope}
    signal = next(s for s in p2.SIGNALS if s.name == term.name)
    return dict(signal.kwargs)


def composite_points(terms: list[Term], board: Any, season: int, week: int, league: str,
                     gain: float) -> dict[str, float]:
    """Apply every term in sequence at `gain * term.lam`. Order does not matter to the product.

    Each term multiplies by `(1 + gain * lam * z)`, and z is computed from the ORIGINAL points in
    every case -- `signals.adjust` standardises the signal, not the points, so the terms commute
    and the composite is not sensitive to the order they are listed in.
    """
    points = dict(board.projected)
    if gain == 0.0:
        return points
    for term in terms:
        try:
            values = _values(term, board, season, week, league)
        except (rank.PreflightError, s7.ScopeMissing):
            continue
        if not values:
            continue
        points = signals.adjust(
            points, board.position, season, gain * term.lam, term.name,
            values=values, **_kwargs(term),
        )
    return points


def weekly_series(terms: list[Term], loaded: dict[p2.Scope, Any],
                  league: str) -> tuple[dict[p2.Scope, float], dict[float, dict[p2.Scope, float]],
                                        dict[float, dict[str, dict[p2.Scope, float]]]]:
    base: dict[p2.Scope, float] = {}
    treated: dict[float, dict[p2.Scope, float]] = {g: {} for g in GAIN_GRID}
    treated_pos: dict[float, dict[str, dict[p2.Scope, float]]] = {
        g: {pos: {} for pos in p2.POSITIONS} for g in GAIN_GRID
    }
    for scope, (board, outcome, baseline) in sorted(loaded.items()):
        season, week = scope
        base[scope] = baseline.rwre
        for pos, value in baseline.per_position.items():
            treated_pos[0.0][pos][scope] = value
        for gain in GAIN_GRID:
            if gain == 0.0:
                treated[gain][scope] = baseline.rwre
                continue
            points = composite_points(terms, board, season, week, league, gain)
            value = rank.vorp_values(points, board.position, league)
            order = sorted(value, key=lambda pid: (-value[pid], pid))
            score = s7.score_week(order, outcome, league, position=board.position)
            treated[gain][scope] = score.rwre
            for pos, held in score.per_position.items():
                treated_pos[gain][pos][scope] = held
    return base, treated, treated_pos


def seasonal_series(terms: list[Term], league: str) -> tuple[dict[int, float],
                                                             dict[float, dict[int, float]]]:
    """The preseason FFA board, treated with the DRAFT-capable terms only."""
    draft_terms = [term for term in terms if term.draft_capable]
    base: dict[int, float] = {}
    treated: dict[float, dict[int, float]] = {g: {} for g in GAIN_GRID}
    sizes = rank.position_pool_sizes(league)
    teams = int(rank.league(league).num_teams)
    pool = rank.pool_size_for(league)
    for season in rank.SEASONS_BY_ARM["ffa"]:
        try:
            loaded = arms.load("ffa", season, league)
            outcome = rank.realised_vorp(rank.realised_per_game(season, league))
        except rank.PreflightError:
            continue

        def _score(points: dict[str, float], loaded: Any = loaded,
                   outcome: dict[str, float] = outcome) -> float:
            order = [
                pid for pid in rank.vorp_order(points, loaded.position, league)
                if pid in outcome
            ]
            return rank.score_board(
                order, outcome, teams=teams, pool_size=pool, position=loaded.position,
                indexing="symmetric", position_pool=sizes,
            ).rwre

        base[season] = _score(loaded.points)
        for gain in GAIN_GRID:
            if gain == 0.0:
                treated[gain][season] = base[season]
                continue
            points = dict(loaded.points)
            for term in draft_terms:
                try:
                    values = p2.values_for(
                        next(s for s in p2.SIGNALS if s.name == term.name),
                        loaded, season, league,
                    )
                except rank.PreflightError:
                    continue
                if not values:
                    continue
                points = signals.adjust(
                    points, loaded.position, season, gain * term.lam, term.name,
                    values=values, **_kwargs(term),
                )
            treated[gain][season] = _score(points)
    return base, treated


def _select_gain(base: dict[Any, float], treated: dict[float, dict[Any, float]],
                 allowed: tuple[int, ...] | None = None) -> float:
    """The gain that minimises RWRE over the allowed seasons. Used for the walk-forward fit."""
    best_gain, best = 0.0, float("inf")
    for gain in GAIN_GRID:
        scores = treated.get(gain, {})
        keys = [
            key for key in scores
            if allowed is None or (key[0] if isinstance(key, tuple) else key) in allowed
        ]
        if not keys:
            continue
        mean = statistics.mean(scores[key] for key in keys)
        if mean < best:
            best, best_gain = mean, gain
    return best_gain


def _mean_over(scores: dict[Any, float], seasons: tuple[int, ...] | None) -> float:
    keys = [
        key for key in scores
        if seasons is None or (key[0] if isinstance(key, tuple) else key) in seasons
    ]
    return statistics.mean(scores[key] for key in keys) if keys else float("nan")


def main(argv: list[str]) -> int:
    league = argv[1] if len(argv) > 1 else "espn_green_hope"
    print(f"S7 PHASE 4 -- the assembled board, {league}")
    print(f"gain grid {GAIN_GRID}, walk-forward fit {FIT} test {TEST}, seed {p2.SEED}")
    print()

    terms, excluded = survivors(league)
    print(f"survivors from phases 2 and 3: {len(terms)}")
    for term in terms:
        kind = "draft-capable" if term.draft_capable else "IN-SEASON ONLY"
        print(f"  {term.name:20s} lambda {term.lam:5.2f}  {term.source}  {kind}  "
              f"effect {term.effect:+.4f}  p {term.p_value:.4f}  scope {term.scope}")
    print(f"excluded: {len(excluded)}")
    for line in excluded:
        print(f"  {line}")
    print()
    if not terms:
        print("NOTHING SURVIVED. There is no composite to assemble, and that is the result of")
        print("this phase rather than a failure of it. The incumbent board stands:")
        for key, value in INCUMBENT.items():
            print(f"  {key} {value}")
        return 0

    loaded = p2.load_scopes(league)
    base, treated, treated_pos = weekly_series(terms, loaded, league)
    print("-- WEEKLY, every surviving term --")
    for gain in GAIN_GRID:
        mean = _mean_over(treated[gain], None)
        print(f"  gain {gain:4.2f}  RWRE {mean:7.4f}  delta {_mean_over(base, None) - mean:+7.4f}")
    selected = _select_gain(base, treated, tuple(FIT))
    print(f"  gain selected on the FIT seasons {FIT}: {selected:4.2f}")
    print(f"  weekly in-sample  {FIT}: baseline {_mean_over(base, FIT):7.4f} -> "
          f"{_mean_over(treated[selected], FIT):7.4f}  "
          f"delta {_mean_over(base, FIT) - _mean_over(treated[selected], FIT):+7.4f}")
    print(f"  weekly OUT-OF-SAMPLE {TEST}: baseline {_mean_over(base, TEST):7.4f} -> "
          f"{_mean_over(treated[selected], TEST):7.4f}  "
          f"delta {_mean_over(base, TEST) - _mean_over(treated[selected], TEST):+7.4f}")
    for pos in p2.POSITIONS:
        before = _mean_over(treated_pos[0.0][pos], TEST)
        after = _mean_over(treated_pos[selected][pos], TEST) if selected else before
        print(f"    {pos} out-of-sample {before:7.4f} -> {after:7.4f}  "
              f"delta {before - after:+7.4f}")
    print()

    draft_terms = [term for term in terms if term.draft_capable]
    in_season = [term for term in terms if not term.draft_capable]
    print(f"-- SEASONAL DRAFT BOARD, {len(draft_terms)} draft-capable terms --")
    if in_season:
        print("   EXCLUDED from the draft board because they read a per-week column that does "
              "not exist in August:")
        for term in in_season:
            print(f"     {term.name}")
    if not draft_terms:
        print("   NO DRAFT-CAPABLE TERM SURVIVED. The weekly gains cannot transfer, because")
        print("   nothing that produced them can be evaluated at a draft. Stated plainly rather")
        print("   than converted into a number.")
        print(f"   incumbent stands: {INCUMBENT[league]}")
        return 0

    sbase, streated = seasonal_series(draft_terms, league)
    espn_seasons = tuple(rank.SEASONS_BY_ARM["espn"])
    ffa_seasons = tuple(sorted(sbase))
    print(f"   FFA seasons {ffa_seasons}   incumbent's espn seasons {espn_seasons}")
    print(f"   incumbent (espn arm, symmetric, its own 6 seasons): {INCUMBENT[league]:7.2f}")
    print(f"   FFA untreated, FFA seasons  {_mean_over(sbase, None):7.2f}")
    print(f"   FFA untreated, espn seasons {_mean_over(sbase, espn_seasons):7.2f}")
    for gain in GAIN_GRID:
        print(f"   gain {gain:4.2f}  FFA seasons {_mean_over(streated[gain], None):7.2f}  "
              f"espn seasons {_mean_over(streated[gain], espn_seasons):7.2f}")
    sel = _select_gain(sbase, streated, tuple(FIT))
    print(f"   gain selected on the FIT seasons {FIT}: {sel:4.2f}")
    print(f"   seasonal in-sample  {FIT}: {_mean_over(sbase, FIT):7.2f} -> "
          f"{_mean_over(streated[sel], FIT):7.2f}")
    print(f"   seasonal OUT-OF-SAMPLE {TEST}: {_mean_over(sbase, TEST):7.2f} -> "
          f"{_mean_over(streated[sel], TEST):7.2f}")
    print()

    weekly_gain = _mean_over(base, TEST) - _mean_over(treated[selected], TEST)
    seasonal_gain = _mean_over(sbase, TEST) - _mean_over(streated[sel], TEST)
    print("-- DOES THE WEEKLY GAIN TRANSFER TO THE DRAFT BOARD --")
    print(f"   weekly out-of-sample gain   {weekly_gain:+7.4f}  "
          f"(material bar {p2.MATERIAL}: {'yes' if abs(weekly_gain) >= p2.MATERIAL else 'NO'})")
    print(f"   seasonal out-of-sample gain {seasonal_gain:+7.4f}  "
          f"(material bar {p2.MATERIAL}: {'yes' if abs(seasonal_gain) >= p2.MATERIAL else 'NO'})")
    transfers = weekly_gain > 0 and seasonal_gain > 0
    print(f"   TRANSFERS: {'yes' if transfers else 'NO'}")
    weekly_positions = [
        _mean_over(treated_pos[0.0][pos], TEST) - _mean_over(treated_pos[selected][pos], TEST)
        for pos in p2.POSITIONS if pos in treated_pos[0.0]
    ]
    better = sum(1 for delta in weekly_positions if delta > 0)
    print(f"   positions improved out-of-sample: {better}/{len(weekly_positions)}")
    if weekly_gain > 0 and better == 0:
        print("   THE BOARD-WIDE WEEKLY GAIN IS NOT PRESENT AT ANY POSITION. It is therefore")
        print("   cross-position reallocation, not better ranking of players against their")
        print("   peers, and the per-position figures are the ones to believe.")
    print()

    print("-- AGAINST THE INCUMBENT, three numbers because two would mislead --")
    untreated_espn = _mean_over(sbase, espn_seasons)
    treated_espn = _mean_over(streated[sel], espn_seasons)
    arm = INCUMBENT[league] - untreated_espn
    print(f"   incumbent, espn arm, its own {len(espn_seasons)} seasons : {INCUMBENT[league]:7.2f}")
    print(f"   UNTREATED FFA arm, same seasons                : {untreated_espn:7.2f}"
          f"   arm difference {arm:+.2f}")
    print(f"   treated FFA arm, same seasons                  : {treated_espn:7.2f}"
          f"   treatment {untreated_espn - treated_espn:+.2f}")
    print("   CAUTION: this line mixes the fit seasons into the mean, because the incumbent bar")
    print("   is quoted over six seasons that include them. The clean number is the")
    print(f"   out-of-sample one above: {_mean_over(sbase, TEST):.2f} -> "
          f"{_mean_over(streated[sel], TEST):.2f}.")
    beats = treated_espn < INCUMBENT[league]
    print(f"   treated board beats the incumbent number: {'yes' if beats else 'NO'}")
    if beats and abs(arm) > abs(untreated_espn - treated_espn):
        print("   BUT MOST OF THAT IS THE ARM, NOT THE RANKING SYSTEM. The untreated FFA board")
        print(f"   already differs from the incumbent by {arm:+.2f} while the treatment is worth")
        print(f"   {untreated_espn - treated_espn:+.2f}. Swapping projection vendors is not the")
        print("   thing this session was testing, and it is not a ranking improvement.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
