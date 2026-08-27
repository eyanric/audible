"""The backtest arms: one scoring function, three orderings, one set of labels.

The question is not "beat consensus". It is: beat seven ESPN-anchored drafters in a half-PPR
8-team 16-round league from seat 8, where the opponents' board is KNOWN -- it is ESPN's own
preseason rank, which is what `espn_ranks_6012_{Y}` holds and what this room demonstrably
drafts from.

    A   ESPN raw            the board the room actually held (`standard` rank)
    B   ESPN re-scored      the same source, re-expressed for a league that pays receptions
    C   full model          B re-ranked by the opportunity adjustment
    C2  opportunity only    the adjustment on its own, with no market anchor

B - A tests the CORE STRATEGY: does re-scoring a known market board for this league's actual
rules beat holding the market board? C - B tests the model's MARGINAL contribution on top of
that, holding the projection source constant so the difference is the adjustment and nothing
else.

SCORING IS ONE FUNCTION. `config.scoring_for(position)` -- WR/TE 0.5 a reception, RB 0.0 --
is used for the labels and for every arm that scores a stat line. `assert_one_scoring` is
called before any fold runs, so a path that quietly used uniform half-PPR or full PPR fails
loudly here instead of producing a plausible number.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config.schema import LeagueConfig

TEAMS = 8
ROUNDS = 16

# Pre-registered, NOT tuned. C interpolates B -> C2 in rank space; 0.5 is the midpoint, the
# same choice correction 2 makes for B itself. Searching this would turn a measurement into
# a fit, so it is fixed before any fold runs and reported as fixed.
C_LAMBDA = 0.5


class ScoringRuleViolation(RuntimeError):
    """The one-scoring rule was broken. Never caught -- the run is invalid, not degraded."""


def assert_one_scoring(config: LeagueConfig) -> None:
    """Fail loudly if any arm could be scored with uniform half-PPR or full PPR.

    League B's reception rule is position-dependent and worth ~30 points a season on a
    pass-catching back -- enough to reorder RB against WR. A backtest that flattened it would
    not look broken; it would quietly answer a question about a different league.
    """
    rb = config.scoring_for("RB").get("rec")
    wr = config.scoring_for("WR").get("rec")
    te = config.scoring_for("TE").get("rec")
    if rb != 0.0:
        raise ScoringRuleViolation(
            f"RB rec must be 0.0 for {config.key}, got {rb!r}. A uniform half-PPR or full-PPR "
            "table would produce this. Labels and arms are both invalid until it is 0.0."
        )
    if wr != 0.5 or te != 0.5:
        raise ScoringRuleViolation(
            f"WR/TE rec must be 0.5 for {config.key}, got WR={wr!r} TE={te!r}."
        )


def rb_reception_points(config: LeagueConfig) -> float:
    """What one RB reception is worth. Exists so a test can assert on the real path."""
    from ..scoring.engine import score_stat_line

    return score_stat_line({"rec": 1.0}, config.scoring_for("RB"))


@dataclass(frozen=True, slots=True)
class Arm:
    """One ordering over players. Lower rank is better, always."""

    name: str
    rank_by_id: dict[str, float]     # sleeper player_id -> rank (1 = best)
    approximate: bool = False
    caveat: str | None = None


def _rank(scores: dict[str, float], *, higher_is_better: bool) -> dict[str, float]:
    ordered = sorted(scores.items(), key=lambda kv: -kv[1] if higher_is_better else kv[1])
    return {pid: i + 1.0 for i, (pid, _) in enumerate(ordered)}


def espn_arms(
    ranks: dict[str, dict[str, object]],
    espn_to_sleeper: dict[str, str],
) -> tuple[Arm, Arm]:
    """Arms A and B from one season's ESPN preseason ranks.

    A is `standard`: through 2025 this league scored standard, so that is literally the order
    the seven opponents held.

    B is per position, per the correction: RB keeps `standard` (a back scores nothing per
    catch here, so PPR order is the wrong direction for him), while WR and TE take the
    MIDPOINT of `standard` and `ppr` -- half-PPR sits between the two boards ESPN publishes.
    QB, K and D/ST keep `standard`; their reception counts round to nothing either way.

    APPROXIMATE. ESPN serves ranks for a past season, not projected points, so B is a blend of
    two ORDERINGS rather than a re-scoring of a projection. It cannot express that one player
    gains more from the reception rule than another at the same rank -- only that WR/TE as a
    class move toward their PPR order. Reported as approximate wherever it appears.
    """
    a_scores: dict[str, float] = {}
    b_scores: dict[str, float] = {}
    for espn_id, row in ranks.items():
        pid = espn_to_sleeper.get(str(espn_id))
        if pid is None:
            continue
        std, ppr = row.get("standard"), row.get("ppr")
        pos = row.get("position")
        if std is None:
            continue
        a_scores[pid] = float(std)  # type: ignore[arg-type]
        if pos in ("WR", "TE") and ppr is not None:
            b_scores[pid] = (float(std) + float(ppr)) / 2.0  # type: ignore[arg-type]
        else:
            b_scores[pid] = float(std)  # type: ignore[arg-type]

    return (
        Arm("A: ESPN raw", _rank(a_scores, higher_is_better=False)),
        Arm(
            "B: ESPN re-scored",
            _rank(b_scores, higher_is_better=False),
            approximate=True,
            caveat="blend of two ESPN ORDERINGS; ESPN serves no projected points for a past "
                   "season, so B cannot re-score a projection",
        ),
    )


def opportunity_arm(
    config: LeagueConfig,
    prior_season: int,
    gsis_to_sleeper: dict[str, str],
) -> Arm:
    """C2: prior-season observed usage, scored through THIS league's rules, ranked.

    Strictly as-of-draft-day for the fold: `ff_opportunity` for season Y-1 is complete before
    the year-Y draft, and nothing else is consulted. No market anchor at all, which is the
    point -- it is the adjustment standing on its own.
    """
    from ..draft.opportunity import modeled_xfp, season_opportunity

    opp = season_opportunity([prior_season])
    positions = _positions_for(prior_season)

    scores: dict[str, float] = {}
    for gsis, xfp in opp.items():
        pid = gsis_to_sleeper.get(str(gsis))
        pos = positions.get(str(gsis))
        if pid is None or pos is None:
            continue
        # scoring_for(position) again -- the same one function the labels use.
        scores[pid] = modeled_xfp(xfp, config.scoring_for(pos))
    return Arm("C2: opportunity only", _rank(scores, higher_is_better=True))


def _positions_for(season: int) -> dict[str, str]:
    from ..adapters.nflverse import opportunity_frame

    df = opportunity_frame([season])
    out: dict[str, str] = {}
    for row in df.select(["player_id", "position"]).iter_rows(named=True):
        pid, pos = row.get("player_id"), row.get("position")
        if pid and pos and str(pid) not in out:
            out[str(pid)] = str(pos)
    return out


def blended_arm(b: Arm, c2: Arm, lam: float = C_LAMBDA) -> Arm:
    """C: B re-ranked by the opportunity adjustment, holding the projection source constant.

    Blending in RANK space rather than point space is what keeps the projection source
    constant: B's points do not exist (it is an ordering), so C cannot be "B's projection plus
    an adjustment". It is B's ORDER, pulled toward the opportunity order by a fixed lambda.
    C - B is therefore exactly the adjustment's marginal contribution and nothing else.

    A player the opportunity model has never seen keeps his B rank untouched, so C never
    penalises a rookie for the model's silence.
    """
    scores: dict[str, float] = {}
    for pid, b_rank in b.rank_by_id.items():
        c2_rank = c2.rank_by_id.get(pid)
        scores[pid] = b_rank if c2_rank is None else (1.0 - lam) * b_rank + lam * c2_rank
    return Arm(
        f"C: full model (lambda={lam})",
        _rank(scores, higher_is_better=False),
        approximate=b.approximate,
        caveat=f"inherits B's approximation; lambda={lam} pre-registered, not tuned",
    )
