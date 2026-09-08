"""MyFantasyLeague as an ADP source, and the first market that is not FantasyFootballCalculator.

WHY A SECOND MARKET AT ALL. Every comparison this project has run is against FFC, which serves
a TWELVE-team board -- `sim/room.py:232` names that outright (`ADP_TEAMS: int = 12`) and the
pinned files agree (`meta.teams` is 12 in all five). Both leagues that matter here are EIGHT.
So every gap this harness has produced carries an unquantified team-count confound, and the
only way to size it is to run the same experiment in a market that is actually eight-team.

MFL's `FCOUNT` is a real filter and not a label, which is the whole reason this source was
chosen. Measured on 2024, same period, same everything else:

    FCOUNT=8   31,133 bytes   245 players (IS_KEEPER=N)
    FCOUNT=12  45,967 bytes

WHAT IS MEASURED HERE, and every number in this docstring was taken from the live API before
anything was built on it:

  * THE YEAR PATH IS VINTAGE. `/2019/export` returns Saquon Barkley, Alvin Kamara, Christian
    McCaffrey, DeAndre Hopkins, Patrick Mahomes, Ezekiel Elliott, Le'Veon Bell -- a 2019 board,
    with a player who was out of the league by 2022 sitting seventh. `/2024/` returns
    McCaffrey, Hill, Lamb, Robinson, Hall. These are not the same list with a different
    filename.
  * THE IDS ARE THE SAME ID SPACE AS THE FFA STAT LINES, EXACTLY AT EIGHT TEAMS AND NOT AT
    TWELVE. 245 of 245 ADP rows for 2024 at FCOUNT=8 join to `sim/data/ffa/raw_stats_2024_wk0.csv`
    on the raw id, with no crosswalk and no name matching. The twelve-team board is a bigger
    pool and reaches past what FFA files: 357 of 363 in 2024, and 318 of 357 in 2021. So the
    exactness is a property of the eight-team pool, not of the id space, and an earlier version
    of this line claimed "251 of 251" for a file that has 245 rows. Stated per market because
    `mfl_12_std` ships and does not have it.
  * NO FOLLOWING-YEAR ROOKIE LEAKS. The 2021 board carries no member of the 2022 draft class
    and the 2024 board none of 2025's, checked against the FFA files' own `draft_year` column.
  * `IS_KEEPER=N` IS NOT OPTIONAL. Left off, 2024 returns 287 drafts; with it, 262. The extra
    25 are keeper and dynasty leagues, whose ADP is a different ordering entirely -- young
    players and rookies are worth more when you keep them. MFL is a dynasty-heavy host, so the
    default is the wrong default here.
  * `PERIOD` FILTERS BY DRAFT DATE and the counts fall as the window narrows: JUNE 271,
    JULY 271, AUG1 268, AUG15 262. `AUG15` is chosen because it is the last window that is
    still entirely pre-season -- the 2024 NFL season opened 5 September -- and it is what
    `ffanalytics`'s `adp_functions.R` uses. `START` is NOT usable: it returns a different top
    three (ids `0651`, `0681`) and 184 drafts, which is a different population, not a later
    window.

WHAT THIS MARKET IS NOT. It is eight-team STANDARD, which matches `espn_green_hope` and the
real 6012 drafts on team count and on scoring. It is not the same POPULATION: MFL drafters are
self-selected hosts of a dynasty-oriented platform, and 2024's board carries a handful of IDP
rows (DL 5, LB 3, DB 4 inside the top 128) which means some of those leagues start defenders.
That contamination is reported rather than filtered, because filtering it would mean deciding
which leagues count.

EVERYTHING IS PINNED. A run must never depend on a live fetch: a DynastyProcess URL started
returning an HTML 404 page on 2026-08-17 and the board could not build. `fetch` writes into
`sim/`'s own cache root and `load_board` reads only from disk, so a network-disabled run either
completes or fails in preflight naming the file it wants.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from . import SIM_CACHE

# The API. The year is a PATH parameter, which is what makes vintage seasons addressable.
BASE = "https://api.myfantasyleague.com/{season}/export"

# A descriptive agent, because MFL asks for one and an anonymous scraper is how a public API
# stops being public.
USER_AGENT = "audible/0.1 (personal fantasy tool; +https://github.com/eyanric/audible)"

# The window. See the module docstring for why AUG15 and why not START.
DEFAULT_PERIOD = "AUG15"

# MFL's position vocabulary -> audible's. `PK` and `Def` are the two that would silently break
# a board if left untranslated: `canon_position` would pass them through and no slot would
# accept them.
POSITION_MAP: dict[str, str] = {
    "PK": "K",
    "Def": "DEF",
    "DE": "DL", "DT": "DL",
    "CB": "DB", "S": "DB",
    "LB": "LB",
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
}

# MFL SPELLS EIGHT TEAMS DIFFERENTLY FROM EVERY OTHER SOURCE IN THIS REPO, and until this
# table existed that was a silent, total join failure rather than a noisy one. `BoardRow.key`
# is `DEF:{team}` for a defence, so `DEF:GBP` and `DEF:GB` are two different players and the
# Packers defence simply never matched an outcome. Measured across all five pinned catalogues,
# the disagreement is exactly these eight and nothing else: every other MFL code appears
# verbatim in `nflverse/teams.parquet`. Note LAR is NOT among them -- MFL and FFC both write
# LAR for the Rams, which is the one collision `room.nick_to_abbr` was written for.
TEAM_ALIASES: dict[str, str] = {
    "GBP": "GB", "JAC": "JAX", "KCC": "KC", "LVR": "LV",
    "NEP": "NE", "NOS": "NO", "SFO": "SF", "TBB": "TB",
}

# MFL's spellings for "not on a roster". They are a real value in the `team` field, not a
# blank, so left alone they would reach `DraftEntry.team` as a franchise that does not exist.
NO_TEAM: frozenset[str] = frozenset({"FA", "FA*", ""})

# Team-aggregate and non-player rows MFL carries in the same catalogue. None can be drafted in
# the formats this repo models, and letting one through would put "Bills, Buffalo" on a board
# as a receiver -- `TMWR` is a real position in MFL's vocabulary.
NON_PLAYER: frozenset[str] = frozenset(
    {"Coach", "Off", "ST", "XX", "PN", "TMQB", "TMRB", "TMWR", "TMTE",
     "TMPK", "TMPN", "TMDB", "TMDL", "TMLB"}
)


def display_name(raw: str) -> str:
    """`"McCaffrey, Christian"` -> `"Christian McCaffrey"`.

    MFL WRITES SURNAME FIRST AND EVERY OTHER SOURCE HERE WRITES GIVEN NAME FIRST, which is a
    total join failure that looks like a working board. `BoardRow.key` is
    `P:{normalize(name)}`, `normalize` does not reorder tokens, so `mccaffrey christian` never
    equals `christian mccaffrey` and EVERY person on an MFL board misses. Measured before this
    function existed: 7 of 180 keys shared between the 2024 MFL and FFC boards, and all seven
    were defences whose three-letter code happened to agree.

    The rule is one comma, and that is measured rather than assumed: all 1,015 skill-position
    rows in the 2024 catalogue carry exactly one, and any suffix rides with the SURNAME ahead
    of it (`"Harrison Jr., Marvin"`, `"Walker III, Kenneth"`). So the suffix lands trailing
    after the swap, which is exactly where `adp_join.normalize` already strips it. A name with
    no comma is returned unchanged rather than guessed at.
    """
    surname, sep, given = raw.partition(",")
    if not sep:
        return raw.strip()
    return f"{given.strip()} {surname.strip()}".strip()


def team_abbr(raw: str) -> str:
    """MFL's team code in the vocabulary the rest of this repo joins on. `""` for no team."""
    code = (raw or "").strip().upper()
    if code in NO_TEAM:
        return ""
    return TEAM_ALIASES.get(code, code)


@dataclass(frozen=True, slots=True)
class MflParams:
    """One MFL market's query, and the filename it pins to.

    Frozen and hashed into the filename so two markets that differ in any parameter cannot
    collide on disk -- an 8-team and a 12-team pin of the same season are different files, and
    that is what makes failure injection 1 possible at all.
    """

    fcount: int = 8
    is_ppr: int = 0
    is_mock: int = 0
    is_keeper: str = "N"
    period: str = DEFAULT_PERIOD

    def slug(self) -> str:
        """EVERY field, in a fixed order. Two of them used to be missing and that was a trap.

        The docstring above has always claimed that markets differing in any parameter cannot
        collide on disk, and `is_keeper` and `is_mock` were not in the slug. `fetch` skips a
        request when the file exists, so a keeper market would have silently ADOPTED the
        redraft pin -- and `meta()` reports `is_keeper` from the params rather than the file,
        so the artifact would have said `Y` over data fetched with `N`. A redraft-vs-keeper
        comparison would then measure exactly 0.0 and report it as a null.
        """
        ppr = "ppr" if self.is_ppr else "std"
        keeper = self.is_keeper.strip().lower() or "n"
        mock = "mock" if self.is_mock else "live"
        return f"{self.fcount}_{ppr}_{keeper}_{mock}_{self.period.strip().lower()}"

    def query(self) -> dict[str, str]:
        return {
            "TYPE": "adp",
            # Upper-cased here so two params that differ only in case cannot send two
            # different queries into what `slug` folds to one filename.
            "PERIOD": self.period.strip().upper(),
            "FCOUNT": str(self.fcount),
            "IS_PPR": str(self.is_ppr),
            "IS_MOCK": str(self.is_mock),
            "IS_KEEPER": self.is_keeper,
            "JSON": "1",
        }


def adp_pin(season: int, params: MflParams) -> str:
    return f"mfl_adp_{params.slug()}_{season}.json"


def players_pin(season: int) -> str:
    return f"mfl_players_{season}.json"


# --- fetching, which happens once and never during a run --------------------------------------


def fetch(season: int, params: MflParams, *, force: bool = False) -> tuple[str, bool]:
    """Pin one season's ADP and the player catalogue it needs. Returns (path, fetched).

    Refuses to overwrite an existing pin unless *force*, because a pinned response is the thing
    that makes a run reproducible and silently refreshing it turns a replay into a new
    experiment.
    """
    import httpx

    root = SIM_CACHE / "mfl"
    root.mkdir(parents=True, exist_ok=True)
    fetched = False
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}) as client:
        for name, query in (
            (adp_pin(season, params), params.query()),
            (players_pin(season), {"TYPE": "players", "DETAILS": "0", "JSON": "1"}),
        ):
            path = root / name
            if path.exists() and not force:
                continue
            resp = client.get(BASE.format(season=season), params=query)
            resp.raise_for_status()
            body = resp.json()
            _assert_shape(body, name, season)
            path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", "utf-8")
            fetched = True
    return str(root / adp_pin(season, params)), fetched


def _assert_shape(body: Any, name: str, season: int) -> None:
    """Refuse to pin something that is not the response we asked for.

    MFL answers 200 with an error envelope rather than a status code for several classes of bad
    request, so a pinned file can be a well-formed apology. Checked at PIN time, because a
    malformed pin discovered mid-run is the failure mode pinning exists to prevent.
    """
    if not isinstance(body, dict) or "error" in body:
        raise ValueError(f"{name}: MFL returned an error envelope for {season}: {body}")
    if "adp" in name:
        rows = ((body.get("adp") or {}).get("player")) or []
        if len(rows) < 100:
            raise ValueError(
                f"{name}: only {len(rows)} ADP rows for {season}. A board that cannot fill a "
                f"128-pick draft is not a board; refusing to pin it."
            )
    else:
        rows = ((body.get("players") or {}).get("player")) or []
        if len(rows) < 1000:
            raise ValueError(f"{name}: only {len(rows)} players for {season}")


# --- reading, which is all a run ever does ----------------------------------------------------


def _read(name: str) -> Any:
    from . import room

    path, _root = room.resolve_input(f"mfl/{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def catalogue(season: int) -> dict[str, tuple[str, str, str]]:
    """MFL id -> (name, audible position, team), non-players dropped."""
    body = _read(players_pin(season))
    out: dict[str, tuple[str, str, str]] = {}
    for row in (body.get("players") or {}).get("player") or []:
        raw = str(row.get("position") or "")
        if raw in NON_PLAYER:
            continue
        position = POSITION_MAP.get(raw)
        if position is None:
            continue
        out[str(row.get("id") or "").strip()] = (
            display_name(str(row.get("name") or "")),
            position,
            team_abbr(str(row.get("team") or "")),
        )
    return out


def board_rows(season: int, params: MflParams, positions: frozenset[str]) -> list[Any]:
    """One season's MFL board as `room.BoardRow`s, ranked by average pick.

    RANK IS DERIVED FROM THE SORT, not read off `rank`, for the same reason `room.load_board`
    derives it from ADP: a rank that comes from the sort cannot silently disagree with the
    number it is meant to summarise. MFL ships a `rank` field and it agrees EXCEPT AT TIES --
    one to six `averagePick` values per file are shared by exactly two players, and the
    `(averagePick, id)` tie-break reverses MFL's order for those pairs. The swap is adjacent
    and deterministic, so no measured number moves; it is recorded because "it agrees" is not
    what the data says.

    Rows whose position the league does not carry are DROPPED, not renamed. An eight-team
    league with no IDP slots cannot draft a linebacker, and leaving him on the board would let
    the room spend a pick on a player no lineup can use.
    """
    from . import room

    body = _read(adp_pin(season, params))
    cat = catalogue(season)
    ranked = sorted(
        ((p, float(p["averagePick"])) for p in (body.get("adp") or {}).get("player") or []),
        key=lambda pair: (pair[1], str(pair[0].get("id"))),
    )
    rows: list[Any] = []
    for row, avg in ranked:
        ident = str(row.get("id") or "").strip()
        hit = cat.get(ident)
        if hit is None:
            continue
        name, position, team = hit
        if position not in positions:
            continue
        rows.append(
            room.BoardRow(
                rank=len(rows) + 1,
                adp=avg,
                name=name,
                position=position,
                team=team,
                stdev=0.0,
                times_drafted=int(row.get("draftsSelectedIn") or 0),
            )
        )
    return rows


def meta(season: int, params: MflParams) -> dict[str, Any]:
    """What the pinned response says about itself: draft count, picks, and the query."""
    body = _read(adp_pin(season, params))
    adp = body.get("adp") or {}
    return {
        "total_drafts": int(adp.get("totalDrafts") or 0),
        "total_picks": int(adp.get("totalPicks") or 0),
        # NOT the ADP window. MFL stamps this when it BUILDS the response, so it reads as today
        # on every request including a 2019 one. Recorded so nobody mistakes it for provenance.
        "generated_at": int(adp.get("timestamp") or 0),
        # HOW MANY DRAFTS THE BOARD IS AN AVERAGE OF, on the page rather than inferred. It is
        # not uniform: 2025's eight-team sample is 124 drafts against 214-267 for 2021-2024,
        # and the thinnest row inside its top 128 appears in 7 drafts against 14-71 elsewhere.
        # A thin cell is a noisy ADP, and `room.SUPPLY_RATIO_CUT`'s comment already blames one
        # for a defence that would not stay on the board.
        "period": params.period,
        "fcount": params.fcount,
        "is_ppr": params.is_ppr,
        "is_keeper": params.is_keeper,
    }


def _count_by(known: dict[str, str], ids: list[str]) -> dict[str, int]:
    """MFL position -> how many of *ids* carry it. Plain, because the first version was not."""
    out: dict[str, int] = {}
    for ident in ids:
        position = known.get(ident, "?")
        out[position] = out.get(position, 0) + 1
    return dict(sorted(out.items()))


def join_rate(season: int, params: MflParams) -> dict[str, Any]:
    """G2. How many ADP rows resolve to a real player, and why any do not.

    THE TWO WAYS A ROW CAN FAIL TO RESOLVE ARE NOT THE SAME THING and the first version of this
    function reported them as one number. 2022 came back at 96.0% and the ten "misses" were
    all `TMQB` -- team-aggregate quarterback rows, "Bills, Buffalo" listed as a passer, which
    some MFL formats draft as a single unit. Those are DELIBERATELY dropped by `NON_PLAYER`;
    counting a correct exclusion as a join failure understates a join that is in fact exact.

    So `unknown` is the number that matters -- an id the catalogue has never heard of, which is
    the crosswalk failure this gate exists to catch -- and `excluded` is reported beside it.
    """
    body = _read(adp_pin(season, params))
    cat = catalogue(season)
    raw = _read(players_pin(season))
    known = {
        str(p.get("id") or "").strip(): str(p.get("position") or "")
        for p in (raw.get("players") or {}).get("player") or []
    }
    ids = [str(p.get("id") or "").strip() for p in (body.get("adp") or {}).get("player") or []]
    hit = [i for i in ids if i in cat]
    excluded = [i for i in ids if i not in cat and i in known]
    unknown = [i for i in ids if i not in known]
    by_position: dict[str, int] = {}
    for i in hit:
        by_position[cat[i][1]] = by_position.get(cat[i][1], 0) + 1
    return {
        "rows": len(ids),
        "matched": len(hit),
        # The gate reads THIS: an id the catalogue cannot name is a broken crosswalk.
        "unknown": len(unknown),
        "unknown_rate": round(len(unknown) / len(ids), 4) if ids else 0.0,
        # Deliberate drops, with the MFL position that caused each, so the reason is legible.
        "excluded": len(excluded),
        "excluded_positions": _count_by(known, excluded),
        "rate": round(len(hit) / len(ids), 4) if ids else 0.0,
        "by_position": dict(sorted(by_position.items())),
        "unknown_ids": unknown[:8],
    }



def main(argv: Sequence[str] | None = None) -> int:
    """Pin every MFL market this repo declares, for every season the room is fitted for.

    THE PINS ARE NOT COMMITTED -- `data/sim-cache/` is gitignored for the same reason
    `data/cache/` is, and the FFA drop is gitignored on the same principle. So this is how a
    fresh checkout gets them, and without it the boards every B8 number was measured on would
    be unreproducible. It refuses to overwrite an existing pin unless `--force`, because
    silently refreshing a pinned response turns a replay into a new experiment.

        uv run python -m sim.mfl              # fetch what is missing
        uv run python -m sim.mfl --check      # say what is missing, fetch nothing
    """
    import argparse

    from . import markets

    parser = argparse.ArgumentParser(prog="python -m sim.mfl", description=str(main.__doc__))
    parser.add_argument("--force", action="store_true", help="re-fetch pins already on disk")
    parser.add_argument("--check", action="store_true", help="report only; fetch nothing")
    args = parser.parse_args(argv)

    from . import room

    wanted = [
        (market, season)
        for market in markets.REGISTRY.values()
        if market.source == "mfl"
        for season in room.SEASONS
    ]
    # DEDUPED, because the player catalogue is shared by every market of a season -- it is not
    # parameterised by FCOUNT -- and counting it once per market would report a file count no
    # directory listing agrees with.
    every = {name for market, season in wanted for name in market.pins(season)}
    missing = sorted(n for n in every if not (SIM_CACHE / n).exists())
    if args.check:
        for name in missing:
            print(f"MISSING {name}")
        print(f"{len(missing)} file(s) missing of {len(every)} wanted")
        return 1 if missing else 0
    for market, season in wanted:
        path, fetched = fetch(season, MflParams(**market.params), force=args.force)
        print(f"{'fetched' if fetched else 'present'}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
