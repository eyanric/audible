"""S3 Task 2 -- one signal at a time, against the noise floor, on a rotated holdout.

ORDERED BY TASK 1, NOT BY THE HANDOFF. The residual diagnostic ranked these by measured
explanatory power; `td_oe` -- the handoff's "strongest prior" -- came twelfth of thirteen with
a sign that flips half the time, so it is not tested here.

THE HOLDOUT IS PARTIALLY BURNED. 2024-2025 was read by `audible#84` (every source headline) and
`audible#85` (the winner, per season, cross-league). No clean out-of-sample win can be reported
there. So every signal is scored by LEAVE-ONE-SEASON-OUT across all available seasons, the full
spread is reported, and the result is labelled SELECTION-CONTAMINATED. It is directional
evidence, not confirmation.

THE NOISE FLOOR. `audible#85` pre-registered a knob that is a sha256 of player and season --
zero information by construction -- and tuning it alone bought +2.317 on its select split. Every
signal here is reported beside that same floor, measured in this regime. **A signal that buys
less than a hash is not a signal.**

G6. Every term must be shown capable of CHANGING AN ORDERING before it is measured. `audible#85`
shipped a `shrink` knob that was provably inert -- uniform scaling of VORP leaves the order
unchanged, and the board was byte-identical at s=0.0 and s=0.4. `can_change_ordering` is the
gate that would have caught it.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from functools import lru_cache

from . import arms, rank, residual

LEAGUE = "espn_green_hope"
SOURCE = "espn"
INDEXING = "symmetric"  # pre-registered in audible#85, unchanged


@lru_cache(maxsize=32)
def signal_values(name: str, season: int) -> dict[str, float]:
    """gsis_id -> the signal's value for *season*, from information available BEFORE it."""
    if name == "noise":
        # The floor. A hash of player and season: reproducible, and information-free by
        # construction. Not an RNG draw, so a candidate scores the same on every run.
        loaded = arms.load(SOURCE, season, LEAGUE)
        return {
            pid: (int(hashlib.sha256(f"{pid}:{season}".encode()).hexdigest()[:8], 16)
                  / 0xFFFFFFFF) * 2.0 - 1.0
            for pid in loaded.position
        }
    prior = residual.prior_facts(season)
    if name == "snap_share":
        return {p: v["prior_snap_share"] for p, v in prior.items() if "prior_snap_share" in v}
    if name == "target_share":
        return {p: v["prior_tgt_share"] for p, v in prior.items() if "prior_tgt_share" in v}
    if name == "td_oe":
        return {p: v["td_oe"] for p, v in prior.items() if "td_oe" in v}
    if name == "draft_round":
        # Lower round is better, so it is negated: the signal is "draft capital", increasing.
        return {p: -v for p, v in residual.draft_round().items()}
    if name == "adp_gap":
        meta = residual.ffa_meta(season)
        loaded = arms.load(SOURCE, season, LEAGUE)
        out: dict[str, float] = {}
        for pos in rank.SCOREABLE:
            members = [
                p for p, q in loaded.position.items()
                if q == pos and p in loaded.points and (meta.get(p, {}).get("adp") or 0) > 0
            ]
            if len(members) < 20:
                continue
            proj = {p: i for i, p in enumerate(sorted(members, key=lambda q: -loaded.points[q]))}
            adp = {p: i for i, p in enumerate(sorted(members, key=lambda q: meta[q]["adp"]))}
            for p in members:
                # POSITIVE means the market likes him more than the projection does.
                out[p] = float(proj[p] - adp[p])
        return out
    if name in NGS_FILES:
        fk, col, _pos = NGS_FILES[name]
        return ngs_prior(fk, col, season)
    if name == "availability":
        rates = position_availability(season)
        loaded = arms.load(SOURCE, season, LEAGUE)
        return {p: rates[q] for p, q in loaded.position.items() if q in rates}
    if name == "contract":
        return contract_value(season)
    if name == "age":
        meta = residual.ffa_meta(season)
        return {p: m["age"] for p, m in meta.items() if m.get("age") == m.get("age")}
    if name == "uncertainty":
        meta = residual.ffa_meta(season)
        return {p: m["sd_rel"] for p, m in meta.items() if m.get("sd_rel") == m.get("sd_rel")}
    raise ValueError(f"unknown signal {name!r}")


# S5. A term is standardised over the CELLS its information varies across.
#
# `position` -- the default -- z-scores within each position, which is right for a term that
# separates players inside a position (separation, rush efficiency, snap share).
#
# `board` z-scores across the whole scoreable pool, and it is the ONLY correct scope for a term
# that is CONSTANT WITHIN A POSITION. `audible#87` ran `availability` -- a position-level
# rate -- through the within-position path, where every member of a position holds the same
# value, `sd` is zero, and the cell is skipped. Nineteen of twenty cells were a literal no-op
# and the twentieth applied 8.95e-16 of floating-point residue. The term was never measured.
SIGNAL_SCOPE: dict[str, str] = {"availability": "board"}

# A standard deviation this far below the cell mean is floating-point residue, not spread.
# `audible#87`'s 2022 quarterback cell held one distinct value and still reported
# sd = 8.95e-16 against mu = 7.97 -- a relative sd of 1.1e-16 -- because the shared value and
# its own mean differ in the last bit. That residue scaled a 66-man block and became the whole
# of a published result. Machine epsilon is 2.2e-16; this sits seven orders of magnitude above.
MIN_SD_REL = 1e-9


@dataclass(frozen=True, slots=True)
class Cell:
    """One standardisation cell: what `adjust` did here, and why."""

    label: str
    n: int
    distinct: int
    mu: float
    sd: float
    applied: bool
    reason: str


def cells(
    points: dict[str, float], position: dict[str, str], season: int, name: str,
    *, rookies_only: bool = False, scope: str | None = None,
    values: dict[str, float] | None = None,
) -> list[Cell]:
    """The cells `adjust` would standardise over, applied or skipped, with the deciding `sd`.

    THE GATE AND THE TRANSFORM SHARE THIS FUNCTION BY CONSTRUCTION. `audible#87`'s G5 asked
    "can this term change an ordering" through one code path and `adjust` decided whether to
    act through another, so a term that never applied still passed the gate. They cannot
    diverge again without this function changing under both.
    """
    vals = signal_values(name, season) if values is None else values
    eligible = set(points)
    if rookies_only:
        prior = residual.prior_facts(season)
        eligible = {p for p in points if p not in prior}
    scope = scope or SIGNAL_SCOPE.get(name, "position")
    if scope == "board":
        groups = [("board", [p for p in eligible
                             if position.get(p) in rank.SCOREABLE and p in vals])]
    elif scope == "position":
        groups = [(pos, [p for p in eligible if position.get(p) == pos and p in vals])
                  for pos in rank.SCOREABLE]
    else:
        raise ValueError(f"unknown scope {scope!r}; expected 'position' or 'board'")

    out: list[Cell] = []
    for label, have in groups:
        if len(have) < 10:
            out.append(Cell(label, len(have), len({vals[p] for p in have}) if have else 0,
                            float("nan"), float("nan"), False, "n < 10"))
            continue
        xs = [vals[p] for p in have]
        mu = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
        floor = MIN_SD_REL * max(1.0, abs(mu))
        if sd <= floor:
            out.append(Cell(label, len(have), len(set(xs)), mu, sd, False,
                            f"sd {sd:.3e} <= {floor:.3e}, floating-point residue"))
            continue
        out.append(Cell(label, len(have), len(set(xs)), mu, sd, True, "applied"))
    return out


def adjust(
    points: dict[str, float], position: dict[str, str], season: int,
    lam: float, name: str, *, rookies_only: bool = False,
    scope: str | None = None, values: dict[str, float] | None = None,
) -> dict[str, float]:
    """`points * (1 + lam * z)`, z the signal's z-score within its standardisation cell.

    ABSENCE IS NOT ZERO. A player with no value for the signal gets NO adjustment at all --
    the same rule the rest of the harness uses. Coding absence as a zero z-score would park him
    on the positional mean and move him on a number nobody measured.

    *rookies_only* restricts the adjustment to players with no prior-season row, which is what
    a draft-capital term must do: G7 asserts it is inert for everyone else.

    *scope* selects the standardisation cell -- see `SIGNAL_SCOPE`. *values* injects the
    signal directly, which is how the floor's salts are drawn without registering each one.
    """
    if lam == 0.0:
        return dict(points)
    vals = signal_values(name, season) if values is None else values
    eligible = set(points)
    if rookies_only:
        prior = residual.prior_facts(season)
        eligible = {p for p in points if p not in prior}
    scope = scope or SIGNAL_SCOPE.get(name, "position")
    out = dict(points)
    for cell in cells(points, position, season, name, rookies_only=rookies_only,
                      scope=scope, values=vals):
        if not cell.applied:
            continue
        if cell.label == "board":
            have = [p for p in eligible
                    if position.get(p) in rank.SCOREABLE and p in vals]
        else:
            have = [p for p in eligible if position.get(p) == cell.label and p in vals]
        for p in have:
            out[p] = points[p] * (1.0 + lam * ((vals[p] - cell.mu) / cell.sd))
    return out


def can_change_ordering(name: str, season: int, lam: float = 0.10, **kw) -> tuple[bool, int]:
    """G6. Does a non-zero weight actually move the board? Returns (moved, players_moved)."""
    loaded = arms.load(SOURCE, season, LEAGUE)
    base = rank.vorp_order(loaded.points, loaded.position, LEAGUE)
    adj = adjust(loaded.points, loaded.position, season, lam, name, **kw)
    after = rank.vorp_order(adj, loaded.position, LEAGUE)
    n = sum(1 for a, b in zip(base, after, strict=False) if a != b)
    return (base != after), n


def score(season: int, lam: float, name: str, **kw) -> float:
    """One season's RWRE under the pre-registered symmetric indexing."""
    loaded = arms.load(SOURCE, season, LEAGUE)
    realised = rank.realised_per_game(season, LEAGUE)
    rv = rank.realised_vorp(realised)
    pts = adjust(loaded.points, loaded.position, season, lam, name, **kw)
    order = [p for p in rank.vorp_order(pts, loaded.position, LEAGUE) if p in rv]
    if not order:
        raise rank.PreflightError(f"no board for {season}")
    return rank.score_board(
        order, rv, teams=int(rank.league(LEAGUE).num_teams),
        pool_size=rank.pool_size_for(LEAGUE), indexing=INDEXING,
    ).rwre


def seasons_for(name: str) -> tuple[int, ...]:
    out = []
    for s in residual.SEASONS:
        try:
            arms.load(SOURCE, s, LEAGUE)
        except rank.PreflightError:
            continue
        if name == "noise" or signal_values(name, s):
            out.append(s)
    return tuple(out)


def loso(name: str, grid: tuple[float, ...], **kw) -> dict[int, tuple[float, float, float]]:
    """Leave-one-season-out. For each season: fit lambda on the OTHERS, score on it.

    Returns season -> (baseline, treated, chosen_lambda). SELECTION-CONTAMINATED, because
    2024-2025 has been read before -- see the module docstring.
    """
    seasons = seasons_for(name)
    out: dict[int, tuple[float, float, float]] = {}
    for held in seasons:
        others = [s for s in seasons if s != held]
        best, best_lam = float("inf"), 0.0
        for lam in grid:
            tot = sum(score(s, lam, name, **kw) for s in others) / len(others)
            if tot < best:
                best, best_lam = tot, lam
        out[held] = (score(held, 0.0, name, **kw), score(held, best_lam, name, **kw), best_lam)
    return out


# --- S4: football data, not projections -----------------------------------------------------

NGS_FILES = {
    "ngs_separation": ("nextgen_rec_s4", "avg_separation", ("WR", "TE")),
    "ngs_cushion": ("nextgen_rec_s4", "avg_cushion", ("WR", "TE")),
    "ngs_rush_eff": ("nextgen_rush_s4", "efficiency", ("RB",)),
    "ngs_time_to_los": ("nextgen_rush_s4", "avg_time_to_los", ("RB",)),
    "ngs_time_to_throw": ("nextgen_pass_s4", "avg_time_to_throw", ("QB",)),
}


@lru_cache(maxsize=32)
def ngs_prior(file_key: str, column: str, season: int) -> dict[str, float]:
    """Season-aggregate Next Gen Stats from season-1. `week == 0` is the season row."""
    import polars as pl

    path = rank.CACHE / "nflverse" / f"{file_key}.parquet"
    if not path.exists():
        raise rank.PreflightError(f"NGS pin missing: {path}")
    f = pl.read_parquet(path)
    sub = f.filter(
        (pl.col("season").cast(pl.Utf8) == str(season - 1))
        & (pl.col("week") == 0)
        & (pl.col("season_type") == "REG")
    )
    if sub.height == 0:
        sub = f.filter(
            (pl.col("season").cast(pl.Utf8) == str(season - 1)) & (pl.col("week") == 0)
        )
    return {
        str(pid): float(v)
        for pid, v in sub.select(["player_gsis_id", column]).drop_nulls().iter_rows()
    }


@lru_cache(maxsize=16)
def position_availability(season: int) -> dict[str, float]:
    """Mean per-position games played, from seasons STRICTLY BEFORE season-1's outcome.

    POSITION-LEVEL BY REQUIREMENT. `audible#71` measured RB 2.58 games missed against WR 3.29
    at ADP <= 100 in 2025 -- the opposite of the folklore -- so the rates are measured, never
    assumed, and no player-level injury term is built.

    NOTE THE STRUCTURAL CONSEQUENCE, which decides where this can be tested: a value constant
    within a position cannot reorder that position. It moves ONLY the cross-position interleave.
    So its per-position RWRE is inert by construction and its locus is the whole board -- the
    exact opposite of the Next Gen signals, which are within-position by nature.
    """
    import polars as pl

    tot: dict[str, list[float]] = {}
    for s in range(2018, season):
        p = rank.CACHE / "nflverse" / f"player_stats_{s}.parquet"
        if not p.exists():
            continue
        f = pl.read_parquet(p).filter(pl.col("season_type") == "REG")
        agg = f.group_by(["player_id", "position"]).agg(pl.len().alias("g"))
        for _pid, pos, g in agg.iter_rows():
            canon = rank.room.canon_position(str(pos or ""))
            if canon in rank.SCOREABLE:
                tot.setdefault(canon, []).append(float(g))
    return {pos: sum(v) / len(v) for pos, v in tot.items() if v}


@lru_cache(maxsize=16)
def contract_value(season: int) -> dict[str, float]:
    """`apy_cap_pct` of the most recent contract signed STRICTLY BEFORE *season*.

    VINTAGE BY CONSTRUCTION: a contract signed during or after the season is a leak, so
    `year_signed < season` is the filter and it is not negotiable. `apy_cap_pct` -- annual
    value as a share of that year's salary cap -- is used rather than raw dollars, because
    the cap roughly doubled across the window and raw value would encode the calendar.
    """
    import polars as pl

    path = rank.CACHE / "nflverse" / "contracts_s4.parquet"
    if not path.exists():
        raise rank.PreflightError(f"contracts pin missing: {path}")
    f = (
        pl.read_parquet(path)
        .filter(pl.col("gsis_id").is_not_null() & pl.col("year_signed").is_not_null())
        .filter(pl.col("year_signed") < season)
        .select(["gsis_id", "year_signed", "apy_cap_pct"])
        .drop_nulls()
    )
    best: dict[str, tuple[int, float]] = {}
    for gsis, yr, pct in f.iter_rows():
        g = str(gsis)
        if g not in best or int(yr) > best[g][0]:
            best[g] = (int(yr), float(pct))
    return {g: v for g, (_y, v) in best.items()}
