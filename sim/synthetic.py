"""A structurally complete season, built in code. Test scaffolding, not data.

The failure injections need something to corrupt. Pointing them at the pinned parquet made
five of the seven gates SKIP in any checkout without `data/cache` -- which is every fresh
clone and every CI run -- and pytest exits 0 on a skip, so the injections reported green in
exactly the situation where they had tested nothing at all.

So the injections corrupt this instead: a season that satisfies every structural invariant
`backfill.inspect_frame` checks, with no files and no network. The real pinned seasons are
still exercised, by the checks that can only be made against real data, and those skip
honestly because there is genuinely nothing to read.

The schedule is the load-bearing part. 32 teams, 18 weeks, one bye each, 272 games:
ten weeks where everybody plays (16 games) and eight where four teams are idle (14 games),
which is 10*16 + 8*14 = 272 and 8*4 = 32 byes, exactly one per team.
"""

from __future__ import annotations

from typing import Any

TEAMS: tuple[str, ...] = tuple(f"T{i:02d}" for i in range(32))
FULL_WEEKS: frozenset[int] = frozenset({1, 2, 3, 4, 13, 14, 15, 16, 17, 18})
BYE_WEEKS: tuple[int, ...] = (5, 6, 7, 8, 9, 10, 11, 12)

# Enough per game to clear inspect_frame's density floor, and spanning every position the
# gate requires. Two of each per team side, plus a kicker.
ROSTER: tuple[str, ...] = (
    "QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "K",
    "LB", "LB", "CB", "CB", "DE", "DE", "DT", "S", "S", "G", "OT", "C", "P",
)


def _schedule() -> list[tuple[int, str, str]]:
    """(week, home, away) for a full 272-game regular season with one bye per team."""
    games: list[tuple[int, str, str]] = []
    for week in range(1, 19):
        if week in FULL_WEEKS:
            playing = list(TEAMS)
        else:
            # Rotate which four sit out, so every team gets exactly one bye across the
            # eight bye weeks.
            idle = BYE_WEEKS.index(week) * 4
            playing = [t for i, t in enumerate(TEAMS) if not idle <= i < idle + 4]
        for i in range(0, len(playing), 2):
            games.append((week, playing[i], playing[i + 1]))
    return games


def season_frame(season: int = 2024, *, post: bool = True) -> Any:
    """A complete synthetic season that passes every structural check."""
    import polars as pl

    rows: list[dict[str, Any]] = []

    def add(week: int, kind: str, home: str, away: str, index: int) -> None:
        game_id = f"{season}_{week:02d}_{away}_{home}_{index}"
        for team in (home, away):
            for slot, position in enumerate(ROSTER):
                rows.append(
                    {
                        "player_id": f"00-{abs(hash((team, slot))) % 9_000_000:07d}",
                        "player_name": f"{team} {position} {slot}",
                        "player_display_name": f"{team} {position} {slot}",
                        "position": position,
                        "season": season,
                        "week": week,
                        "season_type": kind,
                        "game_id": game_id,
                        "team": team,
                        "completions": 1.0, "attempts": 2.0,
                        "passing_yards": 12.0, "passing_tds": 0.0,
                        "passing_interceptions": 0.0, "passing_2pt_conversions": 0.0,
                        "carries": 1.0, "rushing_yards": 4.0, "rushing_tds": 0.0,
                        "rushing_2pt_conversions": 0.0,
                        "receptions": 1.0, "targets": 2.0, "receiving_yards": 9.0,
                        "receiving_tds": 0.0, "receiving_2pt_conversions": 0.0,
                        "fumbles_lost_total": 0.0, "special_teams_tds": 0.0,
                    }
                )

    for index, (week, home, away) in enumerate(_schedule()):
        add(week, "REG", home, away, index)
    if post:
        for index, (home, away) in enumerate(((TEAMS[0], TEAMS[1]), (TEAMS[2], TEAMS[3]))):
            add(19, "POST", home, away, 1000 + index)

    return pl.DataFrame(rows)
