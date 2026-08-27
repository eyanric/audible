"""Tasks 2, 4 and 5: redraft five real seasons, one manager at a time.

    uv run --extra nflverse python scripts/redraft.py

Read-only. Nothing enters the sort. The gate is fixed in docs/pre-registration-redraft.md
(c9c051d), committed before this file existed.

WHAT AUDIBLE IS HERE, precisely, because the claim depends on it. It is NOT the production
VORP board -- that needs projected points, and no uncontaminated historical projection exists
(ESPN serves ranks only; Sleeper's historical projections zero out players who were ruled
out). It is **consensus order plus structure**: FFC preseason ADP for the value ordering,
this league's replacement level for how far down each position is worth reaching, and the
roster-construction slack arithmetic for when need starts binding. Nothing here knows how
any season turned out.

Replacement level with only an ordering is expressed in RANK space: a player's worth is how
many players at his position sit between him and the position's replacement rank. That is
what `replacement_levels` already computes, fed pseudo-points derived from ADP so the
ordering -- and therefore the rostered counts -- is identical to the real machinery's.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import json
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

YEARS = (2021, 2022, 2023, 2024, 2025)
TEAMS, ROUNDS = 8, 16
ERIC_TEAM = 8
MEANINGFUL_MARGIN = 50.0  # pre-registered

SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K")
ELIG = {"QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
        "FLEX": {"RB", "WR", "TE"}, "DEF": {"DEF"}, "K": {"K"}}
FFC_POS = {"PK": "K"}
NORM_XW = {"PK": "K"}
_AMBIGUOUS: dict[int, dict] = {}


def norm(name: str) -> str:
    """Match names across FFC, ESPN and the crosswalk without matching the wrong man."""
    n = str(name).lower()
    n = re.sub(r"[.'`]", "", n)
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    n = re.sub(r"[^a-z ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _defense_ids(league_id: int) -> dict[str, str]:
    """FFC's "San Francisco Defense" -> ESPN's "49ers D/ST" (id -16025).

    These never matched, and the failure was SILENT: zero of thirteen defences resolved every
    year, so the redraft could not take one at all and simply forfeited the D/ST slot in every
    season. A missing join that costs a starting slot looks exactly like a strategy that does
    not value defences, which is why it survived the first read of the results.

    ESPN's D/ST ids are stable across seasons, so a rank sheet from any year maps them all --
    which matters because 2021 and 2022 have no rank sheet of their own.
    """
    import polars as pl

    nick_to_id: dict[str, str] = {}
    for yr in (2025, 2024, 2023):
        rp = REPO / "data" / "cache" / f"espn_ranks_{league_id}_{yr}.json"
        if not rp.exists():
            continue
        for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
            if row.get("position") == "DEF" and row.get("name"):
                nick_to_id.setdefault(norm(str(row["name"]).replace("D/ST", "")), str(eid))

    tp = REPO / "data/cache/nflverse/teams.parquet"
    teams = pl.read_parquet(tp) if tp.exists() else None
    out: dict[str, str] = {}
    if teams is not None:
        for r in teams.iter_rows(named=True):
            nick = norm(str(r.get("team_nick") or ""))
            eid = nick_to_id.get(nick)
            if not eid:
                continue
            # FFC writes the CITY: "San Francisco Defense", "New Orleans Defense"
            city = str(r.get("team_name") or "")
            city = city[: len(city) - len(r.get("team_nick") or "")].strip()
            for key in (f"{city} defense", f"{nick} defense", f"{city} {nick} defense"):
                out[norm(key)] = eid
    return out


def espn_id_by_name(year: int, league_id: int) -> dict[str, str]:
    """Name -> espn_id, preferring that season's own ESPN rank sheet where one exists.

    Ambiguous names are the trap here. ff_playerids carries TWO Lamar Jacksons -- the
    quarterback and a defensive back -- and a plain setdefault took whichever sorted first.
    For 2023-2025 the rank sheet overrode it; for 2021-2022 there is no sheet, so the wrong
    id stuck and the "quarterback" scored zero because that id is absent from actuals. A
    drafted player who cannot score looks exactly like a bust, which is why it survived a
    read of the results and only surfaced when a QB showed 0 in a year he played 12 games.

    So a name resolving to several ids is ranked by presence in that season's actuals
    first, then by whether the crosswalk calls him a fantasy-rosterable position -- which
    separates a quarterback from a cornerback even in a year with no actuals row.
    """
    import polars as pl

    actuals_path = REPO / "data" / "cache" / f"espn_actuals_{league_id}_{year}.json"
    scored = (set(json.loads(actuals_path.read_text(encoding="utf-8")))
              if actuals_path.exists() else set())

    cands: dict[str, list[tuple[str, str]]] = {}
    ids = pl.read_parquet(REPO / "data/cache/nflverse/ff_playerids.parquet")
    for r in ids.select(["name", "espn_id", "position"]).iter_rows(named=True):
        if r["name"] and r["espn_id"] is not None:
            cands.setdefault(norm(r["name"]), []).append(
                (str(r["espn_id"]), NORM_XW.get(r["position"], r["position"]) or ""))

    # A fantasy-rosterable position beats a defensive one. That is what separates the two
    # Lamar Jacksons, and it works even for a name absent from that season's actuals -- which
    # the first version of this fix did not, since it ranked on actuals presence alone.
    fantasy = {"QB", "RB", "WR", "TE", "K", "DEF"}

    def rank(opt: tuple[str, str]) -> tuple[int, int]:
        eid, pos = opt
        return (0 if eid in scored else 1, 0 if pos in fantasy else 1)

    out: dict[str, str] = {}
    for key, options in cands.items():
        out[key] = min(options, key=rank)[0]
    out_pos: dict[str, list[tuple[str, str]]] = cands
    rp = REPO / "data" / "cache" / f"espn_ranks_{league_id}_{year}.json"
    if rp.exists():
        for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
            if row.get("name"):
                out[norm(row["name"])] = str(eid)
    out.update(_defense_ids(league_id))
    _AMBIGUOUS[year] = {k: v for k, v in out_pos.items() if len(v) > 1}
    return out


def replacement_ranks(adp_rows, config) -> dict[str, int]:
    """How deep each position is worth going, from the real replacement machinery.

    Fed pseudo-points that are monotone in ADP, so the ordering -- and therefore the rostered
    counts the baseline is read off -- is exactly what the ranking would produce. Nothing
    about a player's actual season enters.
    """
    from audible.models.player import PlayerProjection
    from audible.value.replacement import replacement_levels

    projs = [
        PlayerProjection(player_id=str(i), name=r["name"], primary_position=r["pos"],
                         eligible_positions=frozenset({r["pos"]}), team=None,
                         points=float(len(adp_rows) - i), stats={})
        for i, r in enumerate(adp_rows) if r["pos"] in config.positions
    ]
    return {p: lv.replacement_rank for p, lv in replacement_levels(projs, config).items()}


def unfilled_slots(positions: list[str]) -> list[str]:
    order = sorted(range(len(SLOTS)), key=lambda i: len(ELIG[SLOTS[i]]))
    pool, out = list(positions), []
    for i in order:
        hit = next((j for j, p in enumerate(pool) if p in ELIG[SLOTS[i]]), None)
        if hit is None:
            out.append(SLOTS[i])
        else:
            pool.pop(hit)
    return out


def lineup_points(roster, points, position) -> float:
    order = sorted(range(len(SLOTS)), key=lambda i: len(ELIG[SLOTS[i]]))
    pool = sorted(roster, key=lambda p: -points.get(p, 0.0))
    used, total = set(), 0.0
    for i in order:
        hit = next((p for p in pool
                    if p not in used and position.get(p) in ELIG[SLOTS[i]]), None)
        if hit is not None:
            used.add(hit)
            total += points.get(hit, 0.0)
    return total


def audible_pick(available, position, pos_rank, repl, my_positions):
    """Consensus order, priced by replacement level, constrained by roster construction."""
    unfilled = unfilled_slots(my_positions)
    picks_left = ROUNDS - len(my_positions)
    need = {p for slot in unfilled for p in ELIG[slot]}
    forced = picks_left <= len(unfilled)

    best, best_val = None, float("-inf")
    for pid in available:
        pos = position.get(pid)
        if pos is None or (forced and pos not in need):
            continue
        # rank-space VORP: how many at his position sit between him and replacement.
        # A player past his position's replacement rank is worth nothing over the wire.
        val = repl.get(pos, 0) - pos_rank[pid]
        if val > best_val:
            best, best_val = pid, val
    if best is None:  # constraint left nothing legal; fall back to raw consensus order
        best = min(available, key=lambda p: pos_rank.get(p, 1e9))
    return best


def run_year(year: int, config, replaced_team: int):
    """One redraft. Seven seats keep their real picks; `replaced_team` gets Audible's."""
    from audible.adapters.ffc import FfcAdapter

    lid = config.league_id
    snap = FfcAdapter().snapshot(year)
    name2id = espn_id_by_name(year, lid)

    adp_rows, position, pos_rank = [], {}, {}
    by_pos_count: dict[str, int] = collections.defaultdict(int)
    for p in sorted(snap.players, key=lambda x: x["adp"]):
        pos = FFC_POS.get(p["position"], p["position"])
        eid = name2id.get(norm(p["name"]))
        adp_rows.append({"name": p["name"], "pos": pos, "eid": eid})
        if eid is None:
            continue
        position[eid] = pos
        by_pos_count[pos] += 1
        pos_rank[eid] = by_pos_count[pos]

    repl = replacement_ranks(adp_rows, config)
    picks = json.loads(
        (REPO / "data" / "cache" / f"espn_draft_{lid}_{year}.json").read_text(encoding="utf-8"))
    actuals = json.loads(
        (REPO / "data" / "cache" / f"espn_actuals_{lid}_{year}.json").read_text(encoding="utf-8"))
    points = {str(k): float(v) for k, v in actuals.items()}
    # the drafted universe also needs positions; the rank sheet carries them for this league
    rp = REPO / "data" / "cache" / f"espn_ranks_{lid}_{year}.json"
    if rp.exists():
        for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
            if row.get("position"):
                position.setdefault(str(eid), row["position"])

    taken: set[str] = set()
    real_roster, new_roster = [], []
    collisions = 0
    for pick in sorted(picks, key=lambda x: x["overall"]):
        pid = str(pick["player_id"])
        if pick["team_id"] == replaced_team:
            avail = [p for p in pos_rank if p not in taken]
            chosen = audible_pick(avail, position, pos_rank, repl,
                                  [position[p] for p in new_roster if p in position])
            new_roster.append(chosen)
            real_roster.append(pid)
            taken.add(chosen)
        else:
            if pid in taken:  # Audible took him; this manager takes the best still available
                collisions += 1
                alt = [p for p in pos_rank if p not in taken]
                pid = min(alt, key=lambda p: pos_rank[p]) if alt else pid
            taken.add(pid)
    return {
        "year": year, "team": replaced_team,
        "real": lineup_points(real_roster, points, position),
        "audible": lineup_points(new_roster, points, position),
        "collisions": collisions,
        "real_roster": real_roster, "new_roster": new_roster,
        "position": position, "points": points, "pos_rank": pos_rank, "repl": repl,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]

    print("=" * 100)
    print("TASK 2/3 -- AUDIBLE vs ERIC'S ACTUAL ROSTER")
    print("=" * 100)
    print(f"  Gate (pre-registered, c9c051d): win >= 4 of 5 seasons, margin > "
          f"{MEANINGFUL_MARGIN:.0f} actual points.\n")
    print(f"  {'year':<6}{'Eric actual':>13}{'Audible':>10}{'margin':>10}{'share':>8}"
          f"{'collisions':>12}   result")
    eric_rows = []
    for yr in YEARS:
        r = run_year(yr, config, ERIC_TEAM)
        margin = r["audible"] - r["real"]
        share = margin / r["real"] * 100 if r["real"] else 0.0
        won = margin > MEANINGFUL_MARGIN
        eric_rows.append({**{k: r[k] for k in ("year", "real", "audible", "collisions")},
                          "margin": margin, "share": share, "won": won})
        print(f"  {yr:<6}{r['real']:>13.1f}{r['audible']:>10.1f}{margin:>+10.1f}"
              f"{share:>+7.1f}%{r['collisions']:>12}   "
              f"{'WIN' if won else ('win but < margin' if margin > 0 else 'loss')}")

    wins = sum(1 for r in eric_rows if r["won"])
    print(f"\n  seasons won by more than {MEANINGFUL_MARGIN:.0f} points: {wins} of 5  ->  "
          f"{'GATE CLEARED' if wins >= 4 else 'GATE NOT CLEARED'}")
    print(f"  mean margin {statistics.mean(r['margin'] for r in eric_rows):+.1f} points "
          f"({statistics.mean(r['share'] for r in eric_rows):+.1f}% of season total)")

    print()
    print("=" * 100)
    print("TASK 4 -- THE SAME PROCEDURE AGAINST EVERY MANAGER")
    print("=" * 100)
    print(f"  {'team':>5}" + "".join(f"{y:>10}" for y in YEARS) + f"{'record':>9}{'mean':>10}")
    all_rows = []
    for team in range(1, TEAMS + 1):
        margins = []
        for yr in YEARS:
            r = run_year(yr, config, team)
            margins.append(r["audible"] - r["real"])
            all_rows.append({"team": team, "year": yr, "margin": r["audible"] - r["real"]})
        w = sum(1 for m in margins if m > MEANINGFUL_MARGIN)
        tag = "  <- Eric" if team == ERIC_TEAM else ""
        print(f"  {team:>5}" + "".join(f"{m:>+10.1f}" for m in margins)
              + f"{w:>6}/5{statistics.mean(margins):>+10.1f}{tag}")
    overall = [r["margin"] for r in all_rows]
    beats = sum(1 for m in overall if m > MEANINGFUL_MARGIN)
    print(f"\n  across all 40 manager-seasons: Audible wins by >{MEANINGFUL_MARGIN:.0f} in "
          f"{beats}/40, mean margin {statistics.mean(overall):+.1f}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"eric": eric_rows, "all": all_rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
