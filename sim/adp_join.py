"""GATE G3 -- does a season's ADP board actually reach weekly rows?

A replay of 2021 draws its board from `ffc_adp_standard_8_2021.json` and its outcomes from
`player_stats_2021`. If a tenth of that board never resolves to weekly rows, every replay on
that season is quietly measuring a different, smaller league than the one it claims to.
So the miss rate is a gate, not a diagnostic.

The join is TWO STAGES and they fail for unrelated reasons, so they are counted separately:

  stage 1 -- IDENTITY. FFC name+position -> ``ff_playerids`` -> ``gsis_id``. FFC's own
    ``player_id`` is a private namespace: 2434 is Christian McCaffrey to FFC and lands on
    Leslie O'Neal, Jake Ryan or Earl Little depending on which id column you read it as.
    Measured across all five seasons, ZERO of the FFC ids match any of the 20 id columns in
    the crosswalk. So the join goes by name, and a stage-1 miss means "this person is not in
    the crosswalk under this name" -- a string problem, fixable with normalisation.

  stage 2 -- APPEARANCE. gsis_id -> rows in ``player_stats_<season>``. A stage-2 miss means
    the crosswalk knew exactly who was meant and that person took no snaps all year. That is
    not a defect and no string work fixes it; Joe Mixon and Brandon Aiyuk missed all of 2025
    and are genuinely absent from it.

Reported denominators matter as much as the rate. Team defences are ~4-9% of an FFC board
and swing season to season; nothing pinned on disk scores a team D/ST at all (player_stats
has no team-defence rows, and ``teams.parquet`` is colours and logo URLs), so counting them
as join failures inflates the headline and makes seasons incomparable. They are reported as
UNSCOREABLE, on their own line, and excluded from the gated rate.

Run it:

    uv run --extra nflverse python -m sim.adp_join
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)

# Generational suffixes, stripped from BOTH sides. They disagree in both directions: FFC
# writes "Aaron Jones Sr." where nflverse writes "Aaron Jones", and "Kenneth Walker" where
# nflverse writes "Kenneth Walker III". Stripping one side only fixes half of them.
SUFFIXES: frozenset[str] = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

# The entire stage-1 miss population across 2021-2025, five seasons, after normalisation:
# five people who go by a short form on one side and their full name on the other. A table
# rather than fuzzy matching, because fuzzy matching that is wrong is worse than a miss --
# it silently attributes one player's season to another. Every entry here was measured, and
# together they take stage-1 identity to 100% in all five seasons.
ALIASES: dict[str, str] = {
    "hollywood brown": "marquise brown",
    "kenny gainwell": "kenneth gainwell",
    "gabe davis": "gabriel davis",
    "michael badgley": "mike badgley",
    "chig okonkwo": "chigoziem okonkwo",
    "joshua palmer": "josh palmer",
}

# FFC calls team defences "Cincinnati Defense" / "NY Giants Defense". There is no person to
# resolve and no row anywhere in player_stats to resolve to.
DEF_POSITIONS: frozenset[str] = frozenset({"DEF", "DST", "D/ST"})

# Measured miss rates excluding team D/ST are 2.4 / 0.0 / 0.0 / 0.6 / 2.0 percent for
# 2021-2025, and every miss is a player who took no snaps that year rather than a join
# defect. The gate sits at 5% -- well clear of the worst observed season, and far below the
# 30% that would make a replay meaningless. It exists so that a crosswalk regression, or an
# FFC file whose naming convention shifts, fails here instead of quietly shrinking the board
# a replay thinks it drafted from.
MAX_MISS_RATE: float = 0.05


def normalize(name: str) -> str:
    """Fold a display name to a join key.

    NFKD-fold and drop combining marks, lowercase, delete everything outside [a-z0-9 ]
    WITHOUT substituting a space -- so "A.J." becomes "aj" and "Ja'Marr" becomes "jamarr"
    rather than "a j" -- then drop trailing generational suffixes.
    """
    folded = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    kept = "".join(c if (c.isalnum() and c.isascii()) or c == " " else "" for c in stripped)
    tokens = kept.split()
    while tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    key = " ".join(tokens)
    return ALIASES.get(key, key)


@dataclass(frozen=True, slots=True)
class BoardPlayer:
    ffc_id: int
    name: str
    position: str
    team: str

    @property
    def is_defense(self) -> bool:
        return self.position.upper() in DEF_POSITIONS


@dataclass(frozen=True, slots=True)
class JoinReport:
    season: int
    total: int
    unscoreable_def: int
    pool: int
    resolved: int
    with_rows: int
    stage1_misses: tuple[str, ...]
    stage2_misses: tuple[str, ...]
    ambiguous: tuple[str, ...]

    @property
    def miss_rate(self) -> float:
        """The gated number: share of the non-defence board that reaches no weekly row."""
        return (self.pool - self.with_rows) / self.pool if self.pool else 0.0

    @property
    def miss_rate_incl_def(self) -> float:
        misses = self.total - self.with_rows
        return misses / self.total if self.total else 0.0


def load_board(season: int, cache: Path) -> list[BoardPlayer]:
    path = cache / f"ffc_adp_standard_8_{season}.json"
    blob = json.loads(path.read_text(encoding="utf-8"))
    return [
        BoardPlayer(
            ffc_id=int(p["player_id"]),
            name=str(p["name"]),
            position=str(p.get("position") or ""),
            team=str(p.get("team") or ""),
        )
        for p in blob.get("players", [])
    ]


def crosswalk_index(id_map_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """normalized name -> the gsis_ids carried under it.

    A list, not a scalar: "Mike Williams" is three different receivers in this crosswalk and
    collapsing them silently would attribute one man's season to another. Ambiguity is
    resolved later, against the season actually being joined, and counted when it happens.

    Name only -- NOT name+position. Position disagrees legitimately across sources for
    two-way players (nflverse has Travis Hunter at CB, FFC has him at WR), and a strict
    position match drops them for no reason.
    """
    index: dict[str, list[str]] = {}
    for row in id_map_rows:
        name = row.get("name")
        gsis = row.get("gsis_id")
        if not name or not gsis:
            continue
        index.setdefault(normalize(str(name)), []).append(str(gsis))
    return index


# FFC's position vocabulary vs nflverse's, where they differ in name rather than in meaning.
# Only used to BREAK A TIE between two people with the same name -- never to reject a lone
# candidate, because position legitimately disagrees for two-way players (nflverse has
# Travis Hunter at CB; FFC drafted him as a WR).
_POSITION_ALIASES: dict[str, frozenset[str]] = {
    "PK": frozenset({"K"}),
    "K": frozenset({"K", "PK"}),
}


def _position_matches(ffc_position: str, nflverse_positions: frozenset[str]) -> bool:
    want = ffc_position.upper()
    allowed = _POSITION_ALIASES.get(want, frozenset({want}))
    return bool(allowed & nflverse_positions)


def resolve_board(
    board: list[BoardPlayer],
    index: dict[str, list[str]],
    weekly: dict[str, tuple[int, frozenset[str]]],
) -> tuple[list[str], list[str], list[str], int]:
    """Run both stages. Returns (stage1_misses, stage2_misses, ambiguous, with_rows).

    *weekly* maps gsis_id -> (REG row count, positions seen) for the season. Row count is
    the stage-2 test and the first tiebreak: where a name carries several gsis_ids, the one
    with rows in THIS season is the one who played in it.

    When more than one of them played, position breaks the tie. It has to: stripping
    generational suffixes is what makes "Kenneth Walker III" match "Kenneth Walker", and the
    same step collapses Michael Carter II (a Jets cornerback) onto Michael Carter (a Jets
    running back). Both played 2021, so row count cannot separate them, and picking the
    wrong one would credit a corner's season to a drafted RB -- silently, and only in the
    seasons where it happens. A name that survives both tiebreaks is reported as genuinely
    ambiguous rather than guessed at.
    """
    stage1: list[str] = []
    stage2: list[str] = []
    ambiguous: list[str] = []
    hits = 0

    for player in board:
        if player.is_defense:
            continue
        candidates = index.get(normalize(player.name))
        if not candidates:
            stage1.append(f"{player.name} ({player.position})")
            continue

        playing = [g for g in candidates if weekly.get(g, (0, frozenset()))[0] > 0]
        if len(playing) > 1:
            by_position = [
                g for g in playing if _position_matches(player.position, weekly[g][1])
            ]
            if len(by_position) == 1:
                playing = by_position
            else:
                ambiguous.append(
                    f"{player.name} ({player.position}) -> {len(playing)} played, "
                    f"{len(by_position)} at that position"
                )

        if playing:
            hits += 1
        else:
            stage2.append(f"{player.name} ({player.position})")

    return stage1, stage2, ambiguous, hits


def join_season(season: int, cache: Path, id_map_rows: list[dict[str, Any]]) -> JoinReport:
    from audible.adapters.cache import FrameCache

    # FrameCache appends "nflverse" to whatever root it is handed, so the cache root goes in
    # as-is and the parquet is read from <cache>/nflverse/player_stats_<season>.parquet.
    frame = FrameCache(cache).get(f"player_stats_{season}")
    if frame is None:
        raise FileNotFoundError(
            f"player_stats_{season} is not pinned in {cache}; run sim.backfill first"
        )

    import polars as pl

    counts = (
        frame.filter(pl.col("season_type") == "REG")
        .group_by("player_id")
        .agg(
            pl.len().alias("rows"),
            pl.col("position").unique().alias("positions"),
        )
    )
    weekly = {
        str(pid): (int(n), frozenset(str(p) for p in pos if p is not None))
        for pid, n, pos in zip(
            counts["player_id"].to_list(),
            counts["rows"].to_list(),
            counts["positions"].to_list(),
            strict=True,
        )
    }

    board = load_board(season, cache)
    index = crosswalk_index(id_map_rows)
    stage1, stage2, ambiguous, hits = resolve_board(board, index, weekly)
    defenses = sum(1 for p in board if p.is_defense)

    return JoinReport(
        season=season,
        total=len(board),
        unscoreable_def=defenses,
        pool=len(board) - defenses,
        resolved=len(board) - defenses - len(stage1),
        with_rows=hits,
        stage1_misses=tuple(stage1),
        stage2_misses=tuple(stage2),
        ambiguous=tuple(ambiguous),
    )


def _default_cache() -> Path:
    # sim's own root -- see sim/__init__.py. `--cache` still overrides.
    from . import SIM_CACHE

    return SIM_CACHE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim.adp_join",
        description="Measure the FFC ADP board -> weekly rows join, per season.",
    )
    parser.add_argument("--cache", type=Path, default=None, help="cache root to read")
    parser.add_argument("--seasons", type=int, nargs="+", default=list(SEASONS))
    parser.add_argument("--verbose", action="store_true", help="name every miss")
    parser.add_argument(
        "--max-miss", type=float, default=MAX_MISS_RATE,
        help=f"fail above this miss rate, excluding team D/ST (default {MAX_MISS_RATE:.2%})",
    )
    args = parser.parse_args(argv)

    cache = args.cache or _default_cache()
    from audible.adapters import nflverse

    id_map_rows = nflverse.load_id_map()

    worst = 0.0
    for season in args.seasons:
        report = join_season(season, cache, id_map_rows)
        print(
            f"{season}: miss {report.miss_rate * 100:.1f}% "
            f"({report.pool - report.with_rows}/{report.pool} of the scoreable board) "
            f"| incl DEF {report.miss_rate_incl_def * 100:.1f}% "
            f"({report.total - report.with_rows}/{report.total})"
        )
        print(
            f"      unscoreable team D/ST {report.unscoreable_def}"
            f" | stage1 identity {len(report.stage1_misses)}"
            f" | stage2 no rows {len(report.stage2_misses)}"
            f" | ambiguous names {len(report.ambiguous)}"
        )
        if args.verbose:
            for label, misses in (
                ("stage1", report.stage1_misses),
                ("stage2", report.stage2_misses),
                ("ambig", report.ambiguous),
            ):
                for miss in misses:
                    print(f"        {label}: {miss}")
        worst = max(worst, report.miss_rate)

    print()
    print(
        f"worst season miss rate (excl DEF): {worst * 100:.1f}% "
        f"| gate {args.max_miss * 100:.1f}%"
    )
    if worst > args.max_miss:
        print("FAIL: a board that does not reach its weekly rows cannot be replayed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
