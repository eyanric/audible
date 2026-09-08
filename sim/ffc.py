"""FantasyFootballCalculator ADP, pinned. The fetcher that produced B1's pins was never in here.

WHY THIS EXISTS. `ffc_adp_standard_8_<season>.json` has been the board every result in this
project was measured against since B1, and until B15 nothing in the repo could produce one.
The five pinned files arrived from outside and `sim/mfl.py` -- a LATER adapter -- was the only
source with a fetch path, a shape check and a refusal to overwrite. Extending to seven seasons
needs two more of these files, and fetching them by hand into a cache would make the two new
seasons the only ones nobody can re-derive.

THE `teams` PARAMETER IS IGNORED FOR A PAST SEASON, and that is the confound `sim/markets.py`
exists to size rather than a bug here. Measured on 2021: `teams=8` and `teams=12` return
byte-identical bodies, both reporting `meta.teams = 12`, both matching the committed pin. So
the filename's `_8_` describes what was ASKED FOR and `meta.teams` describes what came back,
the pins are reproducible from either value, and the twelve-team board under an eight-team
league is the reason `mfl_8_std` was built.

WHAT IS PINNED IS THE WHOLE RESPONSE, envelope included, because `meta.end_date` is what
`room.load_board` reads for the as-of date and `meta.total_drafts` is the only measure of how
thin a season's sample is. 2019 is thin -- 696 drafts against 2,656 in 2021 -- and a caller
that wants to refuse it needs the number rather than a summary of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import SIM_CACHE

BASE = "https://fantasyfootballcalculator.com/api/v1/adp/standard"
USER_AGENT = "audible/0.1 (personal fantasy tool; +https://github.com/eyanric/audible)"

# What was asked for. It does not change the response for a past season -- see the module
# docstring -- and it is what the pin filenames record.
TEAMS = 8

# Positions FFC names differently from everyone else. `PK` is the kicker; `room.load_board`
# maps it, and it is repeated here so a shape check can reject a body missing kickers entirely.
EXPECTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "DEF", "PK"})

# Below this the board cannot fill the room's 128 picks with any depth behind them. It is a
# FLOOR, not a target: 2019 returns 193 against 224-226 elsewhere, which clears it and is
# still the thinnest season in the set, and `sim/runs/b15-seasons.md` reports that rather
# than letting the count pass unremarked.
MIN_PLAYERS = 160


def pin_name(season: int) -> str:
    return f"ffc_adp_standard_{TEAMS}_{season}.json"


def fetch(season: int, *, force: bool = False) -> tuple[Path, bool]:
    """Pin one season's ADP response. Returns (path, whether it went to the network).

    Refuses to overwrite an existing pin unless *force*. A pinned response is what makes a
    replay reproducible, and silently refreshing one turns a replay into a new experiment --
    the same rule `sim/mfl.fetch` follows and for the same reason.

    IT WRITES ONLY INTO `SIM_CACHE`. The five original pins live in the cockpit's own root and
    this never touches it; `room.resolve_input` prefers sim's root and falls back, so a
    seven-season run reads five files from the cockpit and two from here.
    """
    import httpx

    root = SIM_CACHE
    root.mkdir(parents=True, exist_ok=True)
    path = root / pin_name(season)
    if path.exists() and not force:
        return path, False
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(
            BASE, params={"teams": TEAMS, "year": season, "position": "all"}
        )
        resp.raise_for_status()
        body = resp.json()
    assert_shape(body, season)
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path, True


def assert_shape(body: Any, season: int) -> None:
    """Refuse to pin something that is not the response we asked for.

    Checked at PIN time. A malformed pin discovered mid-run is exactly the failure pinning
    exists to prevent, and FFC answers 200 with a `status` field rather than an HTTP code for
    at least one class of bad request.
    """
    if not isinstance(body, dict):
        raise ValueError(f"ffc {season}: response is {type(body).__name__}, not an object")
    if str(body.get("status", "")).lower() != "success":
        raise ValueError(f"ffc {season}: status is {body.get('status')!r}, not Success")
    meta = body.get("meta")
    if not isinstance(meta, dict):
        raise ValueError(f"ffc {season}: no meta block")
    for key in ("teams", "rounds", "total_drafts", "start_date", "end_date"):
        if key not in meta:
            raise ValueError(f"ffc {season}: meta has no {key!r}; load_board reads it")
    if not str(meta["end_date"]).startswith(str(season)):
        raise ValueError(
            f"ffc {season}: meta.end_date is {meta['end_date']!r}, which is not in {season}. "
            f"A board dated to another year is a different season's market."
        )
    players = body.get("players")
    if not isinstance(players, list) or len(players) < MIN_PLAYERS:
        raise ValueError(
            f"ffc {season}: {len(players) if isinstance(players, list) else 'no'} players, "
            f"below the {MIN_PLAYERS} floor. The room drafts {128} and needs depth behind "
            f"them; a short board lets replacement level fall off the end and read 0.0."
        )
    seen = {str(p.get("position") or "") for p in players}
    missing = EXPECTED_POSITIONS - seen
    if missing:
        raise ValueError(
            f"ffc {season}: no rows at position(s) {sorted(missing)}. A board missing a "
            f"position silently removes it from every arm rather than failing."
        )
    for field in ("player_id", "name", "position", "team", "adp", "times_drafted", "stdev"):
        if field not in players[0]:
            raise ValueError(f"ffc {season}: players[0] has no {field!r}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="pin one or more FFC ADP seasons")
    parser.add_argument("seasons", nargs="+", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    for season in args.seasons:
        path, fetched = fetch(season, force=args.force)
        body = json.loads(path.read_text(encoding="utf-8"))
        meta = body["meta"]
        print(
            f"{season}: {'fetched' if fetched else 'already pinned'} {path.name}  "
            f"players={len(body['players'])} drafts={meta['total_drafts']} "
            f"window={meta['start_date']}..{meta['end_date']} teams={meta['teams']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
