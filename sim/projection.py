"""TASK B4/1 -- a walk-forward projected stat line, pre-registered and then left alone.

WHY THIS FILE EXISTS. Every number B1, B2 and B3 produced measured audible's OVERLAY, never
its board, because `seat.board_from_season` hands audible a board whose value is a monotone
transform of ADP rank -- 128 of 128 exact matches, Pearson 1.000000, in all five seasons. The
transform under `src/audible/value/` (replacement level, VORP) never ran on anything real,
because it had nothing real to run on. This builds the missing input: a projection.

IT IS NOT AUDIBLE'S PROJECTION AND NOTHING HERE CLAIMS IT IS. No vintage preseason projection
exists for 2021-2025 in any pinned source; this session looked and did not find one. What
follows is a deliberately plain projection built by this harness so that the TRANSFORM has
something to transform. A conclusion about the transform holds whoever supplies the lines; a
conclusion about audible's projections cannot be drawn here at all.


THE PRE-REGISTRATION
--------------------
The METHOD below was fixed before any arm ran and its parameters have not moved since:
`sim/test_g_b4.py::test_g0_the_pre_registered_constants_are_pinned` asserts every one of them,
so a later edit is a failing gate rather than a silent re-fit.

TWO THINGS WERE AMENDED AFTER THE FIRST RUN AND BOTH ARE DEFECT FIXES RATHER THAN RE-FITS,
which is a distinction worth making in writing rather than leaving to trust:

  the undraftable tail was added, after the first build produced a replacement level of 0.0
  at tight end because the FFC board held fewer tight ends than the league rosters. That is
  a fault in the universe handed to `compute_vorp`, not a parameter. It repairs the four
  scoreable positions only: `POOL_POSITIONS` is {QB, RB, WR, TE}, so D/ST and K still have a
  replacement level of 0.0 and always will, because the scoring vocabulary cannot score them.

  the rookie capital lookup was moved from gsis to name, after adversarial review found the
  gsis lookup could not fire on the rookie path at all -- see `DraftCapital`. That made the
  implementation match the text; the text did not move.

Both improved the projection's accuracy, which is stated here so that it is on the record and
not discovered later: correlation rose in all four seasons. Neither was chosen for that.

For target season S, using ONLY seasons strictly before S inside the pinned window:

  UNIVERSE   the season-S FFC ADP board (`room.load_board(S).rows`), which is the DRAFTABLE
             pool, PLUS every other player with at least one regular-season game INSIDE THE
             S-1/S-2/S-3 lookback window at a scoreable position, who is projected identically
             but can never be drafted.

             THE TAIL IS NOT DECORATION AND LEAVING IT OUT WAS A DEFECT. Replacement level is
             "the best projected player nobody rosters", so it is only meaningful if the pool
             contains more players at a position than the league rosters. The FFC board holds
             18 tight ends in 2025 and league 6012 rosters 18, so replacement fell off the end
             of the list and came back 0.0 -- which handed every tight end his full projection
             as VORP and put Brock Bowers first overall. 2024 was one player from the same
             failure (TE replacement 15.8, the last tight end on the board) and D/ST hit it
             outright. That is an artifact of a truncated universe, not a property of the
             transform: production hands `compute_vorp` the whole rosterable catalog and the
             baseline is always found. The tail restores that, and only the FFC rows are ever
             draftable, so no arm can take a player the room does not know about.

  IDENTITY   each board row -> a gsis id by normalised-name join against the prior seasons'
             own rows, position-checked. A row that never appears in a prior season takes the
             rookie path.

  WEIGHTS    w = (0.6, 0.3, 0.1) over S-1, S-2, S-3, renormalised over the prior seasons in
             which that player has at least one regular-season game.

  GAMES      G = sum_t w_t * games_t, clamped to [1, 17].

  RATE       for each scoring key k, r_k = sum_t w_t * (season total of k in t / games_t).

  ROLE       for S >= 2023, the per-game rate of EVERY lookback season for which
             `ff_opportunity` exists -- not only S-1 -- is regressed HALFWAY TOWARD the role
             its expected-production model implies, for the seven keys this harness blends:

                 r = max(0, actual_ps + 0.5 * (expected_ffo - actual_ffo))

             The adjustment travels as a DIFFERENCE, which is how `ff_opportunity` ships it --
             its own `*_diff` columns are exactly `actual - expected`. That matters because the
             two files do not define yardage identically, and a ratio or a straight average
             would import that definitional gap into every rate; a difference cancels it. Half
             and half is a coin flip, chosen for having no free parameter to fit rather than
             for performing well.

  ROOKIE     no regular-season row in any prior season, so no gsis id either. The line is the
             mean rookie-season per-game line for (position, NFL draft-capital bucket),
             computed over PRIOR seasons only, times that bucket's mean rookie games. Buckets
             on `draft_ovr`: <=32, <=64, <=128, and everything later or undrafted. Capital is
             looked up BY NAME, since these players have no id here. NFL draft position is
             settled in April and a fantasy draft is in August, so it is pre-draft knowledge.

  OUTPUT     `RawPlayerLine` with stats = r_k * G. `pass_yd` is bucketed to 25-yard units per
             game before scaling, matching how the outcome measure scores it. `years_exp` is
             0 exactly when the rookie path was taken, which is the flag `_project_line`
             reads. This league's ADP is injected under `config.adp_market` so the resulting
             board carries `adp_rank` and G2 can compare the two orderings.

THERE IS NO SHRINKAGE TERM AND THAT IS DELIBERATE. The usual reason to shrink a per-game rate
is that a two-game sample produces a wild rate; here that rate is multiplied by a projected
games count derived from the same two games, so the season total is already small and shrinking
it as well would price the short sample twice. The cost is real and is not hidden: a player who
missed most of S-1 through injury is projected on his weighted games and comes out low. A
returning starter is the case this projection is worst at.


WHAT THE HANDOFF SAID WAS AVAILABLE, AND WHAT IS
------------------------------------------------
The brief listed "prior-season stats, snap share, route participation, ff_opportunity, depth
chart slot, rosters, age" and said all were already pinned. Measured, in both cache roots:

    player_stats          2021 2022 2023 2024 2025   all five
    ff_opportunity             2022 2023 2024 2025   no 2021
    snap_counts                          2025        one season
    route_participation                  2025        one season
    depth_chart_slots                    2025 2026   one usable season
    rosters                                   2026   none in window
    ff_playerids          no season; birthdate, draft_year, draft_ovr

Snap share, route participation and depth chart slot exist for 2025 alone. A 2025 file cannot
be a PRIOR-season signal for any season in the window -- for 2025 it is the drafted season
itself, which is leakage, and for 2022-2024 it does not exist. They are therefore unusable
here, and this is a refuted premise rather than a choice.

Age was reachable -- `ff_playerids.birthdate` is a static fact and age at season S is
arithmetic on it -- and is NOT used, because the pre-registration above is the simple form the
brief asked for and adding a term after seeing the data is the thing this session must not do.
`ff_playerids.age` is a 2026-vintage column and would have been leakage in any case.

So 2021 has no prior season inside the window and is NOT USABLE. Usable target seasons are
2022, 2023, 2024 and 2025. That is four season-clusters rather than five, so the intervals
carry 3 degrees of freedom and a t quantile of 3.182 instead of 2.776. The QUANTILE is larger
than every earlier sim report's; the WIDTHS are not uniformly larger, because a width is the
quantile times a standard error and the standard error moved too -- `real - shuffle` comes out
narrower here than in the committed B2 run. The role blend applies to 2023-2025 only, because
it needs `ff_opportunity` for S-1 and 2021 has none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import room
from .adp_join import normalize
from .roundtrip import COLUMN_TO_KEY, bucket25

# Weeks 1-18. `player_stats` is filtered on `season_type`; `ff_opportunity` has no such column
# and must be cut on the week number instead.
REG_WEEKS: tuple[int, ...] = tuple(range(1, 19))

# The sources a projected line may be built from. `ffc_adp_standard_8_<S>` is the ONE
# season-S input and it is pre-draft by construction: FFC's `meta.end_date` is 2021-09-01,
# 2022-09-04, 2023-09-01, 2024-09-01 and 2025-09-01 against kickoffs of 09-09, 09-08, 09-07,
# 09-05 and 09-04, so every board closes before its own season starts -- 2022's is the fourth,
# not the first, which is why the dates are listed rather than summarised. `ff_playerids`
# carries no season at all -- birthdates and NFL draft positions, both settled long before an
# August fantasy draft.
# Everything else must name a season strictly earlier than the one being projected.
SEASONLESS_SOURCES: frozenset[str] = frozenset({"ff_playerids"})
SAME_SEASON_SOURCES: tuple[str, ...] = ("ffc_adp_standard_8_",)


class LeakError(ValueError):
    """Raised when a projected line was built from the season it projects."""


def assert_pre_draft(lines: SeasonLines) -> None:
    """G1. A projection carrying anything the drafted season produced does not run.

    THE ANALOGUE OF `room.assert_pre_draft`, which guards the opponent model's board the same
    way and by the same argument. This one guards the value board. It is deliberately a check
    on PROVENANCE STRINGS rather than on intent, and it is not the only check: the gate that
    matters more makes the drafted season's files unreadable and requires the digest not to
    move, which no amount of correct labelling can fake.

    `actual_lines` must fail this, and a gate asserts that it does. A ceiling that passed a
    leak check would not be a ceiling.
    """
    for name in lines.provenance:
        if name in SEASONLESS_SOURCES:
            continue
        if any(name.startswith(prefix) for prefix in SAME_SEASON_SOURCES):
            if not name.endswith(str(lines.season)):
                raise LeakError(
                    f"{name} is a same-season source for a board of {lines.season} but names "
                    f"a different season"
                )
            continue
        try:
            year = int(name.rsplit("_", 1)[1])
        except (IndexError, ValueError) as exc:
            raise LeakError(
                f"{name!r} has no season in its name, so it cannot be shown to predate "
                f"{lines.season}. Unrecognised sources are refused rather than allowed."
            ) from exc
        if year >= lines.season:
            raise LeakError(
                f"{name} is not strictly before {lines.season}. A projection may use only "
                f"what existed before that season's draft."
            )


# The window this harness has data for. A target season needs at least one season before it.
SEASONS: tuple[int, ...] = room.SEASONS
USABLE: tuple[int, ...] = tuple(s for s in SEASONS if s > min(SEASONS))

# Weights over S-1, S-2, S-3. Renormalised over the seasons a player actually played.
LOOKBACK: tuple[float, ...] = (0.6, 0.3, 0.1)

# How much of the S-1 rate the expected-production view replaces, where it exists.
ROLE_BLEND: float = 0.5

# The keys this harness blends, mapped to `ff_opportunity`'s expected columns. Anything not
# named here keeps its plain weighted average: two-point conversions, first downs and
# interceptions ARE modelled by that file and are deliberately left out, at volumes where the
# expected view is all noise. Fumbles are not modelled by it at all -- it carries
# `rec_fumble_lost`/`rush_fumble_lost` with no `_exp` twin.
# Passing yards are paid in whole 25-yard buckets, and the bucket is applied ONCE, to the
# projected per-game rate. Carrying a pre-bucketed rate through the role adjustment would
# bucket it twice and would also subtract raw `ff_opportunity` yards from bucketed ones, so
# the rate travels raw under this key and becomes `pass_yd` only at output.
PASS_YARDS_RAW: str = "pass_yd_raw"

ROLE_KEYS: dict[str, str] = {
    "rec": "receptions_exp",
    "rec_yd": "rec_yards_gained_exp",
    "rec_td": "rec_touchdown_exp",
    "rush_yd": "rush_yards_gained_exp",
    "rush_td": "rush_touchdown_exp",
    PASS_YARDS_RAW: "pass_yards_gained_exp",
    "pass_td": "pass_touchdown_exp",
}
ROLE_ACTUAL: dict[str, str] = {
    "rec": "receptions",
    "rec_yd": "rec_yards_gained",
    "rec_td": "rec_touchdown",
    "rush_yd": "rush_yards_gained",
    "rush_td": "rush_touchdown",
    PASS_YARDS_RAW: "pass_yards_gained",
    "pass_td": "pass_touchdown",
}

# Rookie draft-capital buckets, on overall NFL draft pick. A round is 32 picks.
CAPITAL_BUCKETS: tuple[int, ...] = (32, 64, 128)

MAX_GAMES: int = 17
# The scoring vocabulary, plus the raw passing-yard carrier that becomes `pass_yd` at output.
STAT_KEYS: tuple[str, ...] = (*sorted(set(COLUMN_TO_KEY.values())), PASS_YARDS_RAW)


# Positions with a scoreable stat line. The pool tail is drawn from these only: adding kickers
# and defences would add rows that project to zero and cannot move a replacement level.
POOL_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})

# How the two halves of the universe are keyed. The prefix is the draftability test and it is
# a prefix rather than a side table so that a board entry carries its own answer.
DRAFTABLE_PREFIX: str = "ffc"
POOL_PREFIX: str = "pool"


@dataclass(frozen=True, slots=True)
class SeasonLines:
    """Every projected line for one target season, plus what it took to build them."""

    season: int
    lines: tuple[Any, ...]  # audible.models.player.RawPlayerLine
    fit_seasons: tuple[int, ...]
    role_seasons: tuple[int, ...]
    matched: int
    rookies: int
    unmatched: int
    # The undraftable tail's size. Reported in the artifact because it is the ONLY input to
    # replacement level, and replacement level is the entire difference between the two arms
    # this session compares. A degenerate tail would reorder `audible_transform` wholesale and
    # move no other number on the page.
    pool: int
    provenance: tuple[str, ...]

    def digest(self) -> str:
        """A content hash over the lines. Two arms sharing a projection must share this."""
        import hashlib
        import json

        payload = [
            {
                "player_id": line.player_id,
                "name": line.name,
                "primary_position": line.primary_position,
                "eligible_positions": sorted(line.eligible_positions),
                "team": line.team,
                "stats": {k: round(v, 9) for k, v in sorted(line.stats.items())},
                "years_exp": line.years_exp,
            }
            for line in self.lines
        ]
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --- prior-season aggregates -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Member:
    """One player in the universe, before any projection is put on him.

    Built once and shared by the projected board and the hindsight board, so those two differ
    in FORESIGHT and in nothing else -- not in who is on them, not in what order the rows
    arrive, not in which position bucket a player sits in.
    """

    player_id: str
    name: str
    position: str
    team: str | None
    gsis: str | None
    adp: float | None

    @property
    def draftable(self) -> bool:
        return self.player_id.startswith(DRAFTABLE_PREFIX)


@dataclass(frozen=True, slots=True)
class SeasonTotals:
    """One prior season, aggregated to what the projection needs and nothing else."""

    season: int
    games: dict[str, int]
    totals: dict[str, dict[str, float]]  # gsis -> key -> season total
    position: dict[str, str]
    by_name: dict[str, list[str]]
    role: dict[str, dict[str, float]]  # gsis -> key -> per-game blended rate, or {}


def _frame(season: int):
    import polars as pl

    path, _root = room.resolve_input(f"nflverse/player_stats_{season}.parquet")
    return pl.read_parquet(path)


def _opportunity(season: int):
    """`ff_opportunity` for *season*, or None when it is not pinned. 2021 is not."""
    import polars as pl

    try:
        path, _root = room.resolve_input(f"nflverse/ff_opportunity_{season}.parquet")
    except FileNotFoundError:
        return None
    return pl.read_parquet(path)


def season_totals(season: int) -> SeasonTotals:
    """Aggregate one season to per-player totals, games, position and the role view.

    REGULAR SEASON ONLY, matching `weekly.weekly_points`. The pinned frames carry weeks 19-22
    and counting them would credit playoff teams with three or four extra games in a rate that
    is then multiplied by seventeen.
    """
    import polars as pl

    reg = _frame(season).filter(pl.col("season_type") == "REG").fill_null(0)

    games: dict[str, int] = {}
    totals: dict[str, dict[str, float]] = {}
    position: dict[str, str] = {}
    by_name: dict[str, list[str]] = {}
    for row in reg.iter_rows(named=True):
        pid = str(row["player_id"])
        games[pid] = games.get(pid, 0) + 1
        bucket = totals.setdefault(pid, dict.fromkeys(STAT_KEYS, 0.0))
        for column, key in COLUMN_TO_KEY.items():
            bucket[key] += float(row.get(column) or 0.0)
        bucket[PASS_YARDS_RAW] += float(row.get("passing_yards") or 0.0)
        position[pid] = room.canon_position(str(row.get("position") or ""))
        name = normalize(str(row.get("player_display_name") or row.get("player_name") or ""))
        if name and pid not in by_name.setdefault(name, []):
            by_name[name].append(pid)

    return SeasonTotals(
        season=season, games=games, totals=totals, position=position,
        by_name=by_name, role=_role_rates(season, games),
    )


def _role_rates(season: int, games: dict[str, int]) -> dict[str, dict[str, float]]:
    """Per-game (expected - actual) from `ff_opportunity`, or {} when the file is absent.

    Divided by the same regular-season game count the actual rate uses, so the two halves of
    the blend are on one denominator.

    THE POSTSEASON FILTER IS LOAD-BEARING AND IT IS NOT THE ONE `player_stats` USES.
    `ff_opportunity` has no `season_type` column at all, and its `week` runs 1 to 22 -- 270 of
    2023's 6,081 rows are postseason. Dividing 22 weeks of expected production by 17 games of
    regular season would inflate every playoff team's role signal, and only theirs. Its `week`
    is Float64 and its `season` is a String, unlike `player_stats`, which is why this filters
    on a float rather than joining.
    """
    import polars as pl

    frame = _opportunity(season)
    if frame is None:
        return {}
    frame = frame.filter(pl.col("week") <= float(max(REG_WEEKS)))
    out: dict[str, dict[str, float]] = {}
    for row in frame.iter_rows(named=True):
        pid = str(row["player_id"])
        played = games.get(pid, 0)
        if not played:
            continue
        bucket = out.setdefault(pid, dict.fromkeys(ROLE_KEYS, 0.0))
        for key, column in ROLE_KEYS.items():
            # The adjustment this season contributes, per the file's own definition of it:
            # expected minus actual, both from `ff_opportunity`, so the units cancel.
            bucket[key] += float(row.get(column) or 0.0) - float(
                row.get(ROLE_ACTUAL[key]) or 0.0
            )
    return {pid: {k: v / games[pid] for k, v in b.items()} for pid, b in out.items()}


# --- the rookie prior --------------------------------------------------------------------


def _capital_bucket(overall: float | None) -> str:
    if overall is None or overall <= 0:
        return "late"
    for edge in CAPITAL_BUCKETS:
        if overall <= edge:
            return f"top{edge}"
    return "late"


@dataclass(frozen=True, slots=True)
class DraftCapital:
    """Overall NFL draft pick, reachable by gsis id AND by normalised name.

    BY NAME IS THE HALF THAT MATTERS AND IT WAS MISSING. The rookie path is entered precisely
    when a board row has NO gsis id -- that is what makes him a rookie to this harness, since
    the id comes from resolving him against prior seasons he did not play in. The lookup was
    `capital.get(member.gsis or "")`, which for a rookie is `capital.get("")`, which is always
    `None`, which buckets to "late". Measured before the fix: 197 of 197 rookie-path members
    across the four seasons landed in "late", including 80 with a real `draft_ovr` -- Cam Ward
    at pick 1, Ashton Jeanty at 6, Caleb Williams at 1, Bijan Robinson at 8. The three capital
    buckets the pre-registration names were unreachable for the only population they exist for.

    The cost was not small. Every rookie at a position shared one line, so the board carried
    large exact-value ties broken by insertion order, which is ADP order -- 19% of scoreable
    rows in 2022 sat in such a tie group, and inside those blocks the board WAS the ADP list,
    which is the failure mode this whole session exists to escape.
    """

    by_gsis: dict[str, float | None]
    by_name: dict[str, float | None]

    def of(self, gsis: str | None, name: str) -> float | None:
        if gsis is not None and gsis in self.by_gsis:
            return self.by_gsis[gsis]
        return self.by_name.get(normalize(name))


def draft_capital() -> DraftCapital:
    """Overall NFL draft pick, from `ff_playerids`.

    A STATIC FACT, not a vintage one. `ff_playerids.age` is as of its own `db_season` (2026)
    and would be leakage; `draft_ovr` is where a player was taken in a draft that had already
    happened, which every fantasy drafter in that August knew.

    A name that maps to two different draft positions is dropped rather than guessed at, for
    the same reason `_resolve_name` refuses an ambiguous name: a wrong draft position silently
    moves a rookie a hundred board places.
    """
    import polars as pl

    path, _root = room.resolve_input("nflverse/ff_playerids.parquet")
    frame = pl.read_parquet(path).select(["gsis_id", "name", "draft_ovr", "draft_year"])
    by_gsis: dict[str, float | None] = {}
    seen: dict[str, set[float | None]] = {}
    for row in frame.iter_rows(named=True):
        value = row.get("draft_ovr")
        overall = float(value) if value is not None else None
        gsis = row.get("gsis_id")
        if gsis:
            by_gsis[str(gsis)] = overall
        name = normalize(str(row.get("name") or ""))
        if name:
            seen.setdefault(name, set()).add(overall)
    by_name = {name: next(iter(v)) for name, v in seen.items() if len(v) == 1}
    return DraftCapital(by_gsis=by_gsis, by_name=by_name)


def rookie_prior(
    fit: dict[int, SeasonTotals], capital: DraftCapital
) -> dict[tuple[str, str], tuple[dict[str, float], float]]:
    """(position, capital bucket) -> (mean per-game line, mean games), over PRIOR seasons.

    A rookie season is identified as a player's FIRST appearance inside the fitting window.
    That is an approximation and it is stated rather than smoothed over: a player who debuted
    in 2019 and first appears here in 2022 is counted as a 2022 rookie. It biases the prior
    toward established players and so makes the rookie line generous, which is the direction
    that hurts this projection's own accuracy rather than flattering it.
    """
    seen: set[str] = set()
    pooled: dict[tuple[str, str], list[tuple[dict[str, float], int]]] = {}
    for season in sorted(fit):
        table = fit[season]
        for pid, played in table.games.items():
            if pid in seen or not played:
                continue
            seen.add(pid)
            key = (table.position.get(pid, ""), _capital_bucket(capital.by_gsis.get(pid)))
            rates = {k: v / played for k, v in table.totals[pid].items()}
            pooled.setdefault(key, []).append((rates, played))

    out: dict[tuple[str, str], tuple[dict[str, float], float]] = {}
    for key, rows in pooled.items():
        n = len(rows)
        mean = {
            k: sum(r[k] for r, _g in rows) / n for k in STAT_KEYS
        }
        out[key] = (mean, sum(g for _r, g in rows) / n)
    return out


# --- the projection ----------------------------------------------------------------------


def universe(season: int, fit: dict[int, SeasonTotals]) -> list[Member]:
    """The draftable FFC rows first, then the undraftable tail, in a fixed order.

    Order is deterministic and does not depend on any projection: board rank for the draftable
    half, then gsis id for the tail. Two boards built from this list therefore agree row for
    row, which is what makes their digests comparable.
    """
    board = room.load_board(season)
    members: list[Member] = []
    claimed: set[str] = set()
    for row in board.rows:
        gsis = _resolve(row, fit)
        if gsis:
            claimed.add(gsis)
        members.append(
            Member(
                player_id=f"{DRAFTABLE_PREFIX}{row.rank:04d}", name=row.name,
                position=row.position, team=row.team, gsis=gsis, adp=float(row.adp),
            )
        )

    # The tail: everyone with prior evidence who the market did not price into this board.
    #
    # RESTRICTED TO THE LOOKBACK WINDOW, which is not a detail. `_rates_for` reads S-1, S-2 and
    # S-3 only, so a player whose sole appearance is S-4 has no projection and would fall
    # through to the rookie branch -- arriving in the pool with a generous draft-capital line
    # and a rookie flag, neither of which is true of him. Measured before this filter: 135 such
    # players in 2025, enough to move a replacement level. The window is the same one the rates
    # use, by construction rather than by coincidence.
    window = {season - offset for offset in range(1, len(LOOKBACK) + 1)}
    seen: dict[str, tuple[str, int]] = {}
    for prior in sorted(fit, reverse=True):
        if prior not in window:
            continue
        table = fit[prior]
        for pid, played in table.games.items():
            if not played or pid in claimed or pid in seen:
                continue
            position = table.position.get(pid, "")
            if position in POOL_POSITIONS:
                seen[pid] = (position, prior)
    for pid in sorted(seen):
        position, prior = seen[pid]
        members.append(
            Member(
                player_id=f"{POOL_PREFIX}:{pid}", name=f"pool {pid}", position=position,
                team=None, gsis=pid, adp=None,
            )
        )
    return members


def _resolve_name(name: str, position: str, fit: dict[int, SeasonTotals]) -> str | None:
    """A name and position -> a gsis id, most recent season first. None when it never appears.

    Ambiguity is resolved by requiring the position to match, and an unresolvable name is left
    to the caller rather than guessed at -- attributing one player's history to another is a
    silent error and a missing history is a loud one.
    """
    key = normalize(name)
    for season in sorted(fit, reverse=True):
        table = fit[season]
        exact = [c for c in table.by_name.get(key, []) if table.position.get(c) == position]
        if len(exact) == 1:
            return exact[0]
    return None


def _resolve(row: room.BoardRow, fit: dict[int, SeasonTotals]) -> str | None:
    """A board row -> a gsis id, using the prior seasons' own rows. None when it never appears.

    THE BOARD'S POSITION GOVERNS, not the evidence's. `_resolve_name` filters candidates on
    `table.position == position`, where *position* is the board row's, and walks back through
    the prior seasons until one of them agrees. So a player the board lists at a position he
    has never played does not resolve at all and takes the rookie path -- which is the right
    failure, because a board row is a claim about how the market will use him.

    An unresolvable or ambiguous name is left to the rookie path rather than guessed at:
    attributing one player's history to another is a silent error and a rookie line is a loud
    one.
    """
    if row.position in ("DEF", "K"):
        return None
    return _resolve_name(row.name, row.position, fit)


def _rates_for(
    gsis: str, target: int, fit: dict[int, SeasonTotals]
) -> tuple[dict[str, float], float, tuple[int, ...]]:
    """Weighted per-game rates and projected games. Returns ({} , 0, ()) with no history."""
    played: list[tuple[int, float, int]] = []
    for offset, weight in enumerate(LOOKBACK, start=1):
        season = target - offset
        table = fit.get(season)
        if table is None:
            continue
        n = table.games.get(gsis, 0)
        if n:
            played.append((season, weight, n))
    if not played:
        return {}, 0.0, ()

    total_weight = sum(w for _s, w, _n in played)
    rates = dict.fromkeys(STAT_KEYS, 0.0)
    games = 0.0
    for season, weight, n in played:
        share = weight / total_weight
        table = fit[season]
        blended = _blend(table, gsis, n)
        for key in STAT_KEYS:
            rates[key] += share * blended[key]
        games += share * n
    return rates, min(MAX_GAMES, max(1.0, games)), tuple(s for s, _w, _n in played)


def _blend(table: SeasonTotals, gsis: str, played: int) -> dict[str, float]:
    """One season's per-game rates, regressed halfway toward the role, where it is known.

    The adjustment is `ROLE_BLEND * (expected - actual)` in `ff_opportunity`'s own units, added
    to the `player_stats` rate. Both terms of the difference come from the same file, so the
    two files' differing yardage definitions cancel instead of being imported. Clamped at zero:
    a per-game rate cannot be negative, and the raw difference can be for a player whose
    expected production is below a fumble-heavy actual.
    """
    actual = {k: v / played for k, v in table.totals[gsis].items()}
    adjust = table.role.get(gsis)
    if not adjust:
        return actual
    out = dict(actual)
    for key in ROLE_KEYS:
        out[key] = max(0.0, actual[key] + ROLE_BLEND * adjust[key])
    return out


def project(season: int, config: Any) -> SeasonLines:
    """Every projected line for *season*, fitted on strictly prior seasons only.

    G1 IS ENFORCED BY CONSTRUCTION, not by intent. `fit` below is keyed on seasons strictly
    less than *season* and there is no other data path in this function: nothing reads
    `player_stats_<season>`, `ff_opportunity_<season>` or any outcome of it, so a leak would
    have to be a new argument rather than a missed filter. `sim/test_g_b4.py` asserts it twice
    -- once on the provenance strings, once by handing this function a season whose own files
    have been made unreadable and requiring it to succeed unchanged.
    """
    priors = tuple(s for s in SEASONS if s < season)
    if not priors:
        raise ValueError(
            f"{season} has no prior season inside {SEASONS}; it is not a usable target. "
            f"Usable targets are {USABLE}."
        )
    fit = {s: season_totals(s) for s in priors}
    capital = draft_capital()
    rookies = rookie_prior(fit, capital)
    members = universe(season, fit)

    lines: list[Any] = []
    draftable = sum(1 for m in members if m.draftable)
    matched = rookie_count = unmatched = pool = 0
    for member in members:
        rates, games, _used = (
            _rates_for(member.gsis, season, fit) if member.gsis else ({}, 0.0, ())
        )
        if rates:
            years_exp = 1
            if member.draftable:
                matched += 1
            else:
                pool += 1
        else:
            # BY NAME, because a rookie has no gsis id here by definition -- see
            # `DraftCapital`. The `or` fallback stays for a bucket a prior season never
            # populated, which happens at S=2022 where the pool is one season deep.
            bucket = _capital_bucket(capital.of(member.gsis, member.name))
            prior = rookies.get((member.position, bucket)) or rookies.get(
                (member.position, "late")
            )
            if prior is None:
                rates, games = dict.fromkeys(STAT_KEYS, 0.0), 1.0
                unmatched += 1
            else:
                rates, games = prior[0], min(MAX_GAMES, max(1.0, prior[1]))
                rookie_count += 1
            years_exp = 0
        lines.append(_line(member, rates, games, years_exp, config))

    role_seasons = tuple(s for s in priors if fit[s].role)
    provenance = tuple(
        [f"ffc_adp_standard_8_{season}"]
        + [f"player_stats_{s}" for s in priors]
        + [f"ff_opportunity_{s}" for s in role_seasons]
        + ["ff_playerids"]
    )
    if matched + rookie_count + unmatched != draftable:
        raise AssertionError(
            f"{season}: {matched}+{rookie_count}+{unmatched} counted against {draftable} "
            f"draftable rows. Every board row lands in exactly one branch or the reported "
            f"match rate is not describing the board."
        )
    return SeasonLines(
        season=season, lines=tuple(lines), fit_seasons=priors, role_seasons=role_seasons,
        matched=matched, rookies=rookie_count, unmatched=unmatched, pool=pool,
        provenance=provenance,
    )


def _line(member: Member, rates: dict[str, float], games: float, years_exp: int, config: Any):
    """One `RawPlayerLine`. The single place a rate becomes a season total."""
    from audible.models.player import RawPlayerLine

    stats = {key: rates[key] * games for key in STAT_KEYS if key != PASS_YARDS_RAW}
    # Bucketed ONCE, on the per-game rate. The outcome measure truncates each WEEK to whole
    # 25-yard units, so the season-level analogue is to truncate the per-game rate and then
    # scale it -- not to truncate the season total, which would be off by up to a bucket a
    # game in the same direction for every quarterback.
    stats["pass_yd"] = bucket25(rates[PASS_YARDS_RAW]) * games
    if member.adp is not None:
        # Only the draftable half carries an ADP, so `adp_rank` is a rank over the market's own
        # list and the pool tail cannot shift it. `_adp_for` reads exactly this key.
        stats[config.adp_market] = member.adp
    return RawPlayerLine(
        player_id=member.player_id,
        name=member.name,
        primary_position=member.position,
        eligible_positions=frozenset({member.position}),
        team=member.team,
        stats=stats,
        ids={},
        years_exp=years_exp,
    )


def actual_lines(season: int, config: Any, *, per_game: bool = True) -> SeasonLines:
    """THE LEAK, and it is labelled one everywhere it is used.

    PER GAME BY DEFAULT, AND THAT IS WHAT MAKES IT A CEILING RATHER THAN A NEAR MISS. The
    outcome measure does not pay season totals. `bootstrap_weeks` draws eighteen weeks from a
    player's OWN observed weeks, so a player who appeared nine times is replayed to a full
    season -- its docstring says so: "every player is handed a bye-free season". A board that
    ordered on realised season totals therefore demoted exactly the players the scorer was
    about to restore, and adversarial review measured the cost: a per-game ordering of the same
    realised lines beat it by +56.0 [+19.0, +93.0] points a season. A ceiling that a trivial
    reordering of its own information beats is not a ceiling.

    So the ceiling arms order on per-game rates. `per_game=False` builds the season-total
    version, which is kept as `hindsight_total` because the gap between them is the size of the
    harness's own indifference to durability, and that belongs on the page rather than in a
    footnote.

    The same universe in the same order, built from the season's OWN realised totals. It is the
    ceiling arm's input: it says what a projection with zero error would have been worth, which
    is the scale every other arm is read against. It must never pass `assert_pre_draft` and a
    gate asserts that it does not.

    The universe is still resolved against PRIOR seasons, so the two boards carry the same rows
    in the same order and differ in foresight alone. A player the prior seasons cannot identify
    is a rookie on both boards; on this one he gets his realised season instead of a
    draft-capital prior, which is exactly the foresight being priced.
    """
    priors = tuple(s for s in SEASONS if s < season)
    fit = {s: season_totals(s) for s in priors}
    members = universe(season, fit)
    table = season_totals(season)
    same_season = {season: table}

    lines: list[Any] = []
    matched = unmatched = 0
    for member in members:
        # A rookie has no prior-season identity, so his realised season is found by resolving
        # him against the drafted season instead. That is a leak and it is the point.
        gsis = member.gsis or (
            _resolve_name(member.name, member.position, same_season) if member.draftable else None
        )
        played = table.games.get(gsis, 0) if gsis else 0
        if gsis and played:
            rates = {k: v / played for k, v in table.totals[gsis].items()}
            games = 1.0 if per_game else float(played)
            matched += 1
        else:
            rates, games = dict.fromkeys(STAT_KEYS, 0.0), 1.0
            unmatched += 1
        lines.append(_line(member, rates, games, 1, config))

    return SeasonLines(
        season=season, lines=tuple(lines), fit_seasons=(season,), role_seasons=(),
        matched=matched, rookies=0, unmatched=unmatched, pool=0,
        provenance=(f"player_stats_{season}", f"ffc_adp_standard_8_{season}"),
    )
