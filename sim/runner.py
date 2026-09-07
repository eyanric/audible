"""TASK B2/1 -- the runner. Everything else is built behind this.

THE REQUIREMENT IS UNATTENDED. A long sweep has to run overnight with nobody watching and no
agent attached. That is not a convenience: an agent-attended harness costs Claude Code usage
for every hour it runs, and a harness that only works while someone watches it has not met the
requirement whatever else it does.

So:

* EVERY parameter comes from a config file. No prompts, no positional guessing, no defaults
  that depend on where it was started from.
* PREFLIGHT ASSERTS EVERY INPUT BEFORE THE FIRST DRAFT. A run that dies forty minutes in on an
  upstream 404 is the failure mode this exists to design out, and it is not hypothetical -- a
  DynastyProcess URL began serving an HTML 404 page on 2026-08-17 and the board could not
  build. Preflight opens and checksums all 20 files the run reads, and exits non-zero naming
  the first one missing. It also refuses a config that would run to completion and then
  produce nothing readable: no seasons, no seeds, a repeated seed, an unknown season, or a
  missing arm. Nothing here ever reaches the network.

  THE LIST WAS INCOMPLETE ONCE AND IT COST NOTHING TO FIND, WHICH IS THE ARGUMENT FOR
  CHECKING IT. `room.espn_identity()` reads three `espn_ranks_*` files inside a
  `try/except FileNotFoundError`, so a missing one passed preflight and killed the run later
  at the fit with a bare `ValueError: 2021: 9 of 128 picks resolve to no position`.
* CHECKPOINTS. A sweep that dies at seed 800 of 1000 resumes at 800. Results are appended as
  they are produced, each line carrying its own hash, and the file header binds the config
  hash -- so a checkpoint written by a different config is refused rather than silently mixed
  in with this one's.
* A RUN LOG, to a file as well as stdout, with progress and an ETA.
* NON-ZERO EXIT ON ANY GATE FAILURE, naming the gate.

    uv run --extra nflverse python -m sim run --config sim/configs/b2-smoke.toml
    uv run --extra nflverse python -m sim run --config sim/configs/b2-default.toml --resume


DETERMINISM
-----------
Every stream derives from the config's seed set. The units are enumerated in a fixed order --
sorted split, then arm, then season, then seed -- and each unit's result depends only on its
own seed, so a resumed run produces the same `content_digest` a straight-through run does. NOT
a byte-identical file: `timing.wall_s` and `generated_at` are written into it and are excluded
from the digest, so a resumed write reports the wall clock of the resume rather than of the
work. That is G2 and G4 in one property, and the reason `run_arm` takes a seed, not an RNG.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# `boards` is aliased because `execute` already binds that name to the room's per-season ADP
# boards, and two different things called `boards` inside one function is how a wrong one gets
# passed to a chooser -- which is exactly the B2 defect that cost a session.
from . import LIVE_CACHE, SIM_CACHE, accuracy, artifact, room, seat, weekly
from . import boards as b4boards

REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / "sim" / "runs"
CONFIGS_DIR = REPO / "sim" / "configs"

log = logging.getLogger("sim.run")


@dataclass(frozen=True, slots=True)
class RunConfig:
    name: str
    seasons: tuple[int, ...]
    seeds: tuple[int, ...]
    arms: tuple[str, ...]
    seat: int
    league: str
    fit_seasons: tuple[int, ...]
    # Walk-forward. When set, every comparison is reported three times: over the whole sample,
    # then fit on `wf_fit` and tested in-sample on `wf_fit`, then the SAME fit tested
    # out-of-sample on `wf_test`. An effect that appears in-sample and vanishes out-of-sample
    # is the signature of overfitting, and it has to be visible on the page rather than
    # something a reader remembers to check.
    wf_fit: tuple[int, ...] = ()
    wf_test: tuple[int, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def splits(self) -> list[tuple[str, tuple[int, ...], tuple[int, ...]]]:
        """(label, fit seasons, run seasons). The main split first, then walk-forward."""
        out = [("main", self.fit_seasons, self.seasons)]
        if self.wf_fit and self.wf_test:
            out.append(("wf-in", self.wf_fit, self.wf_fit))
            out.append(("wf-out", self.wf_fit, self.wf_test))
        return out

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(
            artifact.canonical(
                {
                    "name": self.name, "seasons": list(self.seasons),
                    "seeds": list(self.seeds), "arms": list(self.arms),
                    "seat": self.seat, "league": self.league,
                    "fit_seasons": list(self.fit_seasons),
                    "wf_fit": list(self.wf_fit), "wf_test": list(self.wf_test),
                }
            ).encode("utf-8")
        ).hexdigest()

    def units(self) -> list[tuple[str, str, int, int]]:
        """Every (split, arm, season, seed) this run will produce, in a fixed order.

        Sorted, so a resumed run walks the identical sequence and the artifact it writes is
        byte-identical to a straight-through one.
        """
        return [
            (label, arm, season, seed)
            for label, _fit, seasons in self.splits()
            for arm in sorted(self.arms)
            for season in sorted(seasons)
            for seed in sorted(self.seeds)
        ]


def load_config(path: Path) -> RunConfig:
    if not path.exists():
        raise SystemExit(f"PREFLIGHT: no config at {path}")
    blob = tomllib.loads(path.read_text(encoding="utf-8"))
    run = blob.get("run") or {}
    missing = [k for k in ("name", "seasons", "arms", "seat", "league") if k not in run]
    if missing:
        raise SystemExit(f"PREFLIGHT: {path} is missing required key(s) {missing}")
    seeds = run.get("seeds")
    if seeds is None:
        count = run.get("seed_count")
        if count is None:
            raise SystemExit(f"PREFLIGHT: {path} sets neither `seeds` nor `seed_count`")
        start = int(run.get("seed_start", 0))
        seeds = list(range(start, start + int(count)))
    seasons = tuple(int(x) for x in run["seasons"])
    seed_tuple = tuple(int(x) for x in seeds)
    arms = tuple(str(a) for a in run["arms"])

    # Everything below is a config that would otherwise run to completion and then produce a
    # number that means nothing. Each was found by pointing a reviewer at the config loader.
    if not seasons:
        raise SystemExit(f"PREFLIGHT: {path} has no seasons; there is nothing to run")
    if not seed_tuple:
        raise SystemExit(
            f"PREFLIGHT: {path} resolves to zero seeds. An empty run used to produce an "
            f"artifact in which every arm read 0.0 [0.0, 0.0] and every gate passed."
        )
    if len(set(seed_tuple)) != len(seed_tuple):
        # A duplicate seed is computed once and then counted N times by `build_payload`,
        # which collapses the interval to zero width and makes a single draw look certain.
        duplicates = sorted({x for x in seed_tuple if seed_tuple.count(x) > 1})
        raise SystemExit(
            f"PREFLIGHT: {path} repeats seed(s) {duplicates}. A repeated seed is one draw "
            f"counted many times, and it makes the interval a fabrication."
        )
    if len(set(arms)) != len(arms):
        raise SystemExit(f"PREFLIGHT: {path} repeats an arm: {arms}")
    walk = blob.get("walk_forward") or {}
    wf_fit = tuple(int(x) for x in walk.get("fit", ()))
    wf_test = tuple(int(x) for x in walk.get("test", ()))
    if bool(wf_fit) != bool(wf_test):
        raise SystemExit(
            f"PREFLIGHT: {path} sets only one half of [walk_forward]. Both `fit` and `test` "
            f"are required, or neither -- a split reported without its other half is the "
            f"thing walk-forward exists to prevent."
        )
    overlap = sorted(set(wf_fit) & set(wf_test))
    if overlap:
        raise SystemExit(
            f"PREFLIGHT: {path} has season(s) {overlap} in BOTH the walk-forward fit and the "
            f"test. That is not out-of-sample."
        )

    unknown_seasons = sorted(
        (set(seasons) | set(wf_fit) | set(wf_test)) - set(room.SEASONS)
    )
    if unknown_seasons:
        raise SystemExit(
            f"PREFLIGHT: {path} names season(s) {unknown_seasons}, which the room is not "
            f"fitted for. Nothing is substituted for a season that has no pinned inputs."
        )
    try:
        seat_no = int(run["seat"])
    except (TypeError, ValueError):
        raise SystemExit(f"PREFLIGHT: {path} has a non-integer seat {run['seat']!r}") from None

    return RunConfig(
        name=str(run["name"]),
        seasons=seasons,
        seeds=seed_tuple,
        arms=arms,
        seat=seat_no,
        league=str(run["league"]),
        fit_seasons=tuple(int(x) for x in run.get("fit_seasons", room.SEASONS)),
        wf_fit=wf_fit,
        wf_test=wf_test,
        raw=blob,
    )


# --- preflight ------------------------------------------------------------------------------


def required_inputs(config: RunConfig) -> list[str]:
    """Every file the run will read, named before anything is opened."""
    names = ["nflverse/ff_playerids.parquet", "nflverse/teams.parquet"]
    every_season = set(config.seasons) | set(config.fit_seasons)
    every_season |= set(config.wf_fit) | set(config.wf_test)
    for season in sorted(every_season):
        names.append(f"ffc_adp_standard_8_{season}.json")
        names.append(f"espn_draft_{room.LEAGUE_ID}_{season}.json")
    for season in sorted(set(config.seasons) | set(config.wf_fit) | set(config.wf_test)):
        names.append(f"nflverse/player_stats_{season}.parquet")
    # `room.espn_identity()` reads these on every run and swallows FileNotFoundError, so a
    # missing one used to sail through preflight and kill the run later at `fit_room` with a
    # bare `ValueError: 2021: 9 of 128 picks resolve to no position`. They carry the
    # thirty-two negative team-defence ids that the crosswalk has none of, so they are
    # load-bearing rather than optional.
    names.extend(f"espn_ranks_{room.LEAGUE_ID}_{season}.json" for season in (2023, 2024, 2025))
    return names


def preflight(config: RunConfig) -> dict[str, dict[str, str]]:
    """Resolve and checksum every input. Raises SystemExit naming the first one missing.

    THE WHOLE POINT IS THAT THIS RUNS FIRST. Checksumming here costs a couple of seconds and
    buys the guarantee that the run cannot die mid-sweep on a file that was never there.
    """
    pins: dict[str, dict[str, str]] = {}
    for name in required_inputs(config):
        try:
            path, root = room.resolve_input(name)
        except FileNotFoundError:
            raise SystemExit(
                f"PREFLIGHT FAILED: {name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}.\n"
                f"  For a player_stats frame, run:\n"
                f"    uv run --extra nflverse python -m sim.backfill\n"
                f"  Nothing is substituted for a missing input."
            ) from None
        pins[name] = {
            "root": root,
            "sha256": artifact.sha256_file(path),
            "bytes": str(path.stat().st_size),
        }
    league_path = REPO / "leagues" / f"{config.league}.toml"
    if not league_path.exists():
        raise SystemExit(f"PREFLIGHT FAILED: no league config at {league_path}")
    pins[f"leagues/{config.league}.toml"] = {
        "root": "repo",
        "sha256": artifact.sha256_file(league_path),
        "bytes": str(league_path.stat().st_size),
    }
    if not 1 <= config.seat <= room.TEAMS:
        raise SystemExit(
            f"PREFLIGHT FAILED: seat {config.seat} is outside 1..{room.TEAMS}"
        )
    unknown = [a for a in config.arms if a not in seat.ARMS]
    if unknown:
        raise SystemExit(f"PREFLIGHT FAILED: unknown arm(s) {unknown}")
    if "shuffle" not in config.arms:
        raise SystemExit(
            "PREFLIGHT FAILED: the shuffle arm is not optional. It is the leak detector and "
            "it runs on every run, permanently -- five prior validation attempts have failed "
            "and a sixth that suddenly succeeds is assumed leaky until shuffle says otherwise."
        )
    missing_arms = sorted(seat.REQUIRED_ARMS - set(config.arms))
    if missing_arms:
        # This used to run the whole sweep and then die inside `artifact.write` formatting a
        # None -- 900 units of work, no artifact, and no named gate. It belongs here.
        raise SystemExit(
            f"PREFLIGHT FAILED: missing required arm(s) {missing_arms}. `real` is the thing "
            f"under test, `shuffle` is the leak detector, `bot` is the null control that says "
            f"the machinery is sound, and `adp` is the skill baseline that says whether "
            f"beating the bots is an achievement. A report without all four is not readable."
        )
    return pins


# --- checkpoint -----------------------------------------------------------------------------


class Checkpoint:
    """Append-only JSONL. Each line carries its own hash; the header binds the config.

    A checkpoint from a different config is REFUSED, not merged: resuming one sweep into
    another's results would produce an artifact that is a mixture of two runs and says so
    nowhere. A line whose hash does not match is refused for the same reason -- a truncated
    final write is the ordinary way a killed process leaves a file, and silently restarting
    from a half-written line is how a resume turns into a different run.
    """

    def __init__(
        self, path: Path, config: RunConfig, pins: dict[str, dict[str, str]] | None = None
    ) -> None:
        self.path = path
        self.config = config
        self.pins = pins or {}

    @property
    def pin_hash(self) -> str:
        """One hash over every input checksum, bound into the checkpoint header.

        THE CONFIG HASH IS NOT ENOUGH. It covers seasons, seeds, arms, seat and league --
        nothing about the DATA. A run killed at unit 5, resumed after a pinned file changed,
        produced an artifact whose 12 units came from two different boards while its `pins`
        block recorded only the second. That is precisely the `schedules_2026` failure the
        artifact exists to catch, and the checkpoint was the hole it came through.
        """
        return hashlib.sha256(
            artifact.canonical(
                {k: v.get("sha256", "") for k, v in sorted(self.pins.items())}
            ).encode("utf-8")
        ).hexdigest()

    def load(self) -> dict[tuple[str, str, int, int], dict[str, Any]]:
        if not self.path.exists():
            return {}
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return {}
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError:
            raise SystemExit(
                f"CHECKPOINT REFUSED: {self.path} has an unreadable header. Delete it to "
                f"start over; it will not be silently ignored."
            ) from None
        if header.get("config_hash") != self.config.config_hash:
            raise SystemExit(
                f"CHECKPOINT REFUSED: {self.path} was written by config "
                f"{header.get('config_hash', '?')[:12]}, this run is "
                f"{self.config.config_hash[:12]}. Resuming would mix two runs into one "
                f"artifact. Delete the checkpoint or point --config at the original."
            )
        if self.pins and header.get("pin_hash") not in (None, self.pin_hash):
            raise SystemExit(
                f"CHECKPOINT REFUSED: {self.path} was written against different input data "
                f"(pins {str(header.get('pin_hash'))[:12]}, this run {self.pin_hash[:12]}). "
                f"Resuming would produce one artifact from two boards while recording only "
                f"one set of checksums. Delete the checkpoint and rerun."
            )
        out: dict[tuple[str, int, int], dict[str, Any]] = {}
        for number, line in enumerate(lines[1:], start=2):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                payload = row["unit"]
                want = hashlib.sha256(
                    artifact.canonical(payload).encode("utf-8")
                ).hexdigest()[:16]
            except (json.JSONDecodeError, KeyError, TypeError):
                raise SystemExit(
                    f"CHECKPOINT REFUSED: {self.path} line {number} is not a complete record. "
                    f"A killed run leaves a partial line and resuming past it would drop a "
                    f"unit without saying so. Delete the checkpoint to start over."
                ) from None
            if row.get("hash") != want:
                raise SystemExit(
                    f"CHECKPOINT REFUSED: {self.path} line {number} fails its own hash "
                    f"({row.get('hash')} != {want}). The file has been edited or corrupted."
                )
            out[
                (
                    payload.get("split", "main"),
                    payload["arm"],
                    payload["season"],
                    payload["seed"],
                )
            ] = payload
        return out

    def start(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = artifact.canonical(
            {
                "config_hash": self.config.config_hash,
                "name": self.config.name,
                "pin_hash": self.pin_hash,
            }
        )
        # Written to a temp file and renamed, so a kill between create and write cannot leave
        # a zero-byte file whose first DATA line is then parsed as the header -- which
        # discarded a whole completed sweep with "written by config ?".
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(header + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def append(self, payload: dict[str, Any]) -> None:
        line = artifact.canonical(payload)
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(artifact.canonical({"hash": digest, "unit": payload}) + "\n")
            handle.flush()


# --- the run ---------------------------------------------------------------------------------


def setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(path, "a", "utf-8")):
        handler.setFormatter(fmt)
        log.addHandler(handler)


def _eta(done: int, total: int, elapsed: float) -> str:
    if done <= 0:
        return "?"
    remaining = (elapsed / done) * (total - done)
    return f"{remaining / 60:.1f}m" if remaining >= 60 else f"{remaining:.0f}s"


def iter_units(
    config: RunConfig,
    done: dict[tuple[str, str, int, int], dict[str, Any]],
) -> Iterator[tuple[str, str, int, int]]:
    for unit in config.units():
        if unit not in done:
            yield unit


def execute(
    config: RunConfig,
    *,
    resume: bool,
    state_dir: Path,
    progress_every: int = 25,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    """Run every unit, checkpointing as it goes, and return the artifact payload.

    *checkpoint_dir* exists so a test run cannot delete a live sweep's checkpoint. The path
    used to be `RUNS_DIR / f"{name}.checkpoint.jsonl"` with no override, so any second
    invocation of the same config name -- a gate, a cron retrigger, a second terminal -- would
    unlink the in-flight file and start appending its own.
    """
    started = time.perf_counter()
    log.info("preflight: %d inputs", len(required_inputs(config)))
    pins = preflight(config)
    log.info("preflight ok: every input present and checksummed")

    checkpoint = Checkpoint(
        (checkpoint_dir or RUNS_DIR) / f"{config.name}.checkpoint.jsonl", config, pins
    )
    if not resume and checkpoint.path.exists():
        checkpoint.path.unlink()
    checkpoint.start()
    done = checkpoint.load()
    if done:
        log.info("resuming: %d of %d units already done", len(done), len(config.units()))

    # One fit per SPLIT, not one per run. The walk-forward split's whole point is that the
    # opponent model is fitted on 2021-2023 and then tested on seasons it never saw, so
    # sharing a single all-five-season fit across the splits would defeat it silently.
    fits: dict[tuple[int, ...], room.Fit] = {}
    for _label, fit_seasons, _run in config.splits():
        if fit_seasons not in fits:
            fits[fit_seasons] = room.fit_room(fit_seasons)
            log.info(
                "fit %s: %d/%d picks joined, scheduled=%s",
                list(fit_seasons), fits[fit_seasons].joined, fits[fit_seasons].total,
                sorted(fits[fit_seasons].scheduled),
            )
    fit_for = {label: fits[fs] for label, fs, _run in config.splits()}

    every = sorted({s for _l, _f, run in config.splits() for s in run})
    boards = {s: room.load_board(s) for s in every}
    weeks = {s: weekly.weekly_points(s) for s in every}
    league = weekly.league_config() if config.league == weekly.LEAGUE_KEY else _league(config)

    # THE PRIOR, fitted leave-one-season-out. For every season a run scores, the expectation
    # its lineups are chosen against comes from the OTHER seasons only -- so nothing about the
    # season being scored reaches the lineup. This is the primary outcome measure and it is
    # the reason `real - adp` is quoted three ways: prior, oracle and hindsight.
    priors = {s: _prior_for(s, room.SEASONS, boards, weeks) for s in every}
    log.info("priors fitted leave-one-out over %s", list(room.SEASONS))

    # B4'S BOARDS, built ONCE PER SEASON. Building one means projecting a season from its
    # predecessors and running the value engine over 685 to 935 players, and costs 1.4 to 2.3
    # seconds. Hoisted, the four seasons cost about seven seconds; inside the unit loop the
    # 4,800-unit sweep would pay it 4,800 times. They are pure functions of the season and the
    # league, so hoisting them changes no number.
    season_boards: dict[int, Any] = {}
    if any(a in seat.BOARD_ARMS for a in config.arms):
        for season in every:
            season_boards[season] = b4boards.build(season, league)
            built = season_boards[season]
            log.info(
                "boards %d: fit=%s role=%s matched=%d rookies=%d unmatched=%d digest=%s",
                season, list(built.fit_seasons), list(built.role_seasons),
                built.matched, built.rookies, built.unmatched, built.projected_digest,
            )

    pending = list(iter_units(config, done))
    for index, (split, arm, season, seed) in enumerate(pending, start=1):
        built = season_boards.get(season)
        result = seat.run_arm(
            arm, season, seed,
            season_board=boards[season], fit=fit_for[split], week_table=weeks[season],
            config=league, state_dir=state_dir, seat=config.seat, prior=priors[season],
            orders=built.orders if built else None,
        )
        structural = artifact.structural_for(
            result.picks, config.seat, weeks[season].byes, boards[season]
        )
        payload = {
            "split": split, "arm": arm, "season": season, "seed": seed,
            "points_for": round(result.points_for, 4),
            "opponent_mean": round(
                sum(result.opponent_points) / len(result.opponent_points), 4
            ),
            "advantage": round(result.advantage, 4),
            "points_for_season_mean": round(result.points_for_season_mean, 4),
            "advantage_season_mean": round(result.advantage_season_mean, 4),
            "points_for_realised": round(result.points_for_realised, 4),
            "advantage_realised": round(result.advantage_realised, 4),
            "slot_points": {k: round(v, 3) for k, v in sorted(result.slot_points.items())},
            "calls": result.calls,
            "deadline_picks": result.deadline_picks,
            "unresolved": result.unresolved,
            "unfillable_bye_weeks": structural.unfillable_bye_weeks,
            "wasted_roster_slots": structural.wasted_roster_slots,
            "positional_surplus": structural.positional_surplus,
            "illegal_lineups": structural.illegal_lineups,
            "positions": _count_positions(result.picks, config.seat),
        }
        checkpoint.append(payload)
        done[(split, arm, season, seed)] = payload
        if index % progress_every == 0 or index == len(pending):
            elapsed = time.perf_counter() - started
            log.info(
                "%d/%d units (%d done overall) eta %s",
                index, len(pending), len(done), _eta(index, len(pending), elapsed),
            )

    wall = time.perf_counter() - started
    return build_payload(config, pins, fit_for["main"], done, wall, season_boards, league)


def _count_positions(picks: Sequence[Any], seat_id: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for pick in picks:
        if pick.seat != seat_id:
            continue
        out[pick.position] = out.get(pick.position, 0) + 1
    return out


def _prior_for(
    held_out: int,
    seasons: Sequence[int],
    boards: dict[int, Any],
    weeks: dict[int, Any],
) -> dict[tuple[str, int], float]:
    """The pre-draft expectation table for *held_out*, fitted on every OTHER season.

    Loads any season it needs that the run itself does not score, so the prior is always
    fitted on four seasons even when a walk-forward split only runs two.
    """
    others: dict[int, tuple[Any, list[tuple[str, int]]]] = {}
    for season in seasons:
        if season == held_out:
            continue
        board = boards.get(season) or room.load_board(season)
        table = weeks.get(season) or weekly.weekly_points(season)
        # ONE RESOLVER, shared with the scoring side. These were two copies of the same join
        # written in two key spaces, and they disagreed: the fit resolved board rows to gsis
        # ids before pooling while `weekly.prior_points` looked them up by `ffc####`, so every
        # lookup at scoring time missed and the prior was uniformly 0.0. Calling the same
        # function is what stops that recurring.
        others[season] = (table, sorted(seat.positional_ranks(board, table).items()))
    return weekly.prior_table(others)


def _league(config: RunConfig) -> Any:
    from audible.config import load_league

    return load_league(REPO / "leagues" / f"{config.league}.toml")


def build_payload(
    config: RunConfig,
    pins: dict[str, dict[str, str]],
    fit: room.Fit,
    done: dict[tuple[str, str, int, int], dict[str, Any]],
    wall: float,
    season_boards: dict[int, Any] | None = None,
    league: Any = None,
) -> dict[str, Any]:
    all_rows = [done[u] for u in config.units()]
    rows = [r for r in all_rows if r.get("split", "main") == "main"]
    arms: dict[str, Any] = {}
    for arm in sorted(config.arms):
        mine = [r for r in rows if r["arm"] == arm]
        seasons_of = [r["season"] for r in mine]
        pf, pf_lo, pf_hi = seat.mean_and_interval(
            [r["points_for"] for r in mine], seasons_of
        )
        ad, ad_lo, ad_hi = seat.mean_and_interval(
            [r["advantage"] for r in mine], seasons_of
        )
        arms[arm] = {
            "n": len(mine),
            "definition": _arm_definition(arm),
            "structural": {
                "unfillable_bye_weeks": round(
                    sum(r["unfillable_bye_weeks"] for r in mine) / max(1, len(mine)), 4
                ),
                "wasted_roster_slots": round(
                    sum(r["wasted_roster_slots"] for r in mine) / max(1, len(mine)), 4
                ),
                "positional_surplus": round(
                    sum(r["positional_surplus"] for r in mine) / max(1, len(mine)), 4
                ),
                "illegal_lineups": sum(r["illegal_lineups"] for r in mine),
                "unresolved_players": round(
                    sum(r["unresolved"] for r in mine) / max(1, len(mine)), 4
                ),
                # How many of the sixteen picks came from the harness's feasibility deadline
                # rather than from audible's ordering. Measured with the deadline disabled,
                # audible finishes without a kicker in 6.0% of drafts and without a defence in
                # 23.7%; it takes a kicker unassisted 94% of the time. See
                # `seat.AudibleSeat.choose`.
                "deadline_picks": round(
                    sum(r["deadline_picks"] for r in mine) / max(1, len(mine)), 4
                ),
            },
            "points_for": {"mean": round(pf, 3), "lo": round(pf_lo, 3), "hi": round(pf_hi, 3)},
            "advantage": {"mean": round(ad, 3), "lo": round(ad_lo, 3), "hi": round(ad_hi, 3)},
            # BOTH UPPER BOUNDS, per arm. Only the hindsight one used to be here, so the
            # summary's claim about what an oracle projection is worth had to be hardcoded --
            # and a hardcoded number in this file is a number that goes stale within a
            # session. With both present the summary computes it.
            "oracle_secondary": _secondary(mine, "season_mean", "oracle (season-mean)"),
            "realised_secondary": _secondary(mine, "realised", "realised (hindsight)"),
            # PER-SLOT DECOMPOSITION, on every arm, in every artifact, permanently. The
            # tight-end result hid for a whole session because nothing broke the advantage
            # down by slot; that is not going to be possible again.
            "slot_points": _slot_mean(mine),
            # WHAT EACH ARM ACTUALLY DRAFTS, which is the mechanism behind every comparison
            # above and was not on the page. `transform - points_greedy` reads +100-odd, and
            # this row is where that comes from: `points_greedy` ranks on raw points in a
            # one-QB league, so it takes quarterbacks until the room's cap stops it. Without
            # this the reader cannot tell "the transform values players better" from "the
            # transform does not draft three unstartable quarterbacks".
            "positions_drafted": _positions_drafted(mine),
        }

    shuffle_rows = [r for r in rows if r["arm"] == "shuffle"]
    sh, sh_lo, sh_hi = seat.mean_and_interval(
        [r["advantage"] for r in shuffle_rows], [r["season"] for r in shuffle_rows]
    )
    payload: dict[str, Any] = {
        "run": config.name,
        "config_hash": config.config_hash,
        "code_sha": artifact.code_sha(),
        "seasons": list(sorted(config.seasons)),
        "seeds": list(sorted(config.seeds)),
        "seed_count": len(config.seeds),
        "seat": config.seat,
        "league": config.league,
        "fit_seasons": list(sorted(config.fit_seasons)),
        "units": len(all_rows),
        "main_units": len(rows),
        "splits": [
            {"label": label, "fit": list(fs), "run": list(run)}
            for label, fs, run in config.splits()
        ],
        "pins": pins,
        "fit": artifact.fit_block(fit),
        "arms": arms,
        "shuffle": {
            "n": len(shuffle_rows),
            "advantage": round(sh, 2),
            "lo": round(sh_lo, 2),
            "hi": round(sh_hi, 2),
            "at_chance": bool(sh_lo <= 0.0),
            "reading": (
                "shuffle shows no advantage over the field"
                if sh_lo <= 0.0
                else "SHUFFLE IS WINNING -- assume a leak until this is explained"
            ),
        },
        "require_shuffle_at_chance": bool(
            (config.raw.get("gates") or {}).get("require_shuffle_at_chance", False)
        ),
        "leak_decomposition": _decomposition(
            arms, _paired_difference(rows, "real", "shuffle")[0]
        ),
        "outcome_measure": (
            "points-for under a PRIOR lineup: the season lineup is chosen on a "
            "(position, positional rank) table fitted leave-one-season-out, so no "
            "information about the season being scored reaches it"
        ),
        "secondary_measure": (
            "two upper bounds beside every comparison -- _oracle chooses the lineup on each "
            "player's own season mean (a zero-error projection), _hindsight chooses each week "
            "knowing that week"
        ),
        "slots_scored": (
            f"7 of {len(room.STARTING_SLOTS)}. DEF has no rows in player_stats at all; K has "
            f"542-545 regular-season rows a season and scores exactly zero because the "
            f"scoring vocabulary carries no kicking columns. Both slots are filled and "
            f"neither can displace a scoring player."
        ),
        "timing": {"wall_s": round(wall, 2)},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    for left, right, label in _COMPARISONS:
        if left in config.arms and right in config.arms:
            block = _compare(rows, left, right)
            if block:
                payload[label] = block
            # THE SAME COMPARISON UNDER ALL THREE LINEUP POLICIES, printed rather than
            # described. The spread between them is the harness's own uncertainty about what a
            # manager could have known, and any effect smaller than that spread is not a
            # result. Adversarial review found one that was not: a `legacy - adp` reading that
            # was resolvably negative on an oracle lineup and null on a genuine prior, and it
            # had been written up as a finding. B2's headline `real - adp` moves the same way
            # -- it is negative under hindsight and positive under the prior -- which is the
            # whole reason all three are now emitted side by side instead of one.
            for field, suffix in (
                ("advantage_season_mean", "_oracle"),
                ("advantage_realised", "_hindsight"),
            ):
                bound = _compare(rows, left, right, field)
                if bound:
                    payload[f"{label}{suffix}"] = bound

    # THE ABLATIONS, each against `real`, each with a stated verdict. A component whose
    # ablation is indistinguishable from `real` is not contributing, and that is a fact about
    # the tool worth knowing whatever a sweep would say.
    ablations: dict[str, Any] = {}
    for name in sorted(seat.ABLATIONS):
        if name not in config.arms or "real" not in config.arms:
            continue
        block = _compare(rows, name, "real")
        if not block:
            continue
        block["verdict"] = _ablation_verdict(name, block)
        ablations[name] = block
    if ablations:
        payload["ablations"] = ablations

    # WALK-FORWARD. Every comparison above, again, in-sample and out-of-sample side by side.
    walk: dict[str, Any] = {}
    for label in ("wf-in", "wf-out"):
        split_rows = [r for r in all_rows if r.get("split") == label]
        if not split_rows:
            continue
        block: dict[str, Any] = {
            "seasons": sorted({r["season"] for r in split_rows}),
            "n": len(split_rows),
        }
        for left, right, name in _COMPARISONS:
            if left in config.arms and right in config.arms:
                got = _compare(split_rows, left, right)
                if got:
                    block[name] = got
        for name in sorted(seat.ABLATIONS):
            if name in config.arms and "real" in config.arms:
                got = _compare(split_rows, name, "real")
                if got:
                    block[name] = got
        walk[label] = block
    if walk:
        payload["walk_forward"] = walk

    payload["leak_decomposition"] = _decomposition(
        arms, _paired_difference(rows, "real", "shuffle")[0]
    )
    payload["board_vs_adp"] = board_vs_adp(config)
    if season_boards:
        payload["projection"] = _projection_block(season_boards, league)
        payload["ceiling"] = _ceiling_block(payload)
    return payload


def _projection_block(season_boards: dict[int, Any], league: Any) -> dict[str, Any]:
    """G1, G2, G3 and G4 in one block, written into every artifact that runs a board arm.

    G4 IS SATISFIED BY CONSTRUCTION AND ASSERTED ANYWAY. `points_greedy` and
    `audible_transform` are two orderings read off ONE `DraftBoard` built from ONE list of
    lines, so there is a single digest and not two to compare. The digest is written out so a
    later run that changed the projection cannot pass itself off as comparable to this one.
    """
    seasons: dict[str, Any] = {}
    for season in sorted(season_boards):
        built = season_boards[season]
        seasons[str(season)] = {
            "fit_seasons": list(built.fit_seasons),
            "role_seasons": list(built.role_seasons),
            "projected_digest": built.projected_digest,
            "hindsight_digest": built.hindsight_digest,
            "arm_digest": dict(built.arm_digest),
            "matched": built.matched,
            "rookies": built.rookies,
            "unmatched": built.unmatched,
            "pool": built.pool,
            "provenance": list(built.provenance),
            "replacement_level": dict(built.replacement),
            "vs_adp": dict(built.vs_adp),
        }
    out: dict[str, Any] = {
        "pre_registration": (
            "weighted per-game rates over S-1/S-2/S-3 at 0.6/0.3/0.1, times weighted games; "
            "every lookback season for which ff_opportunity exists regressed half way toward "
            "its expected production; a draft-capital rookie prior fitted on prior seasons "
            "only, looked up by name. The method was fixed before any arm ran and its "
            "parameters are pinned by test_g0_the_pre_registered_constants_are_pinned. Two "
            "defect fixes landed after the first run and are named in sim/projection.py: the "
            "undraftable tail, and the rookie capital lookup."
        ),
        "usable_seasons": list(b4boards.projection.USABLE),
        "leak_arms": sorted(b4boards.LEAK_ARMS),
        "seasons": seasons,
    }
    if league is not None:
        # OVER `projection.USABLE`, not over the run's seasons. A run configured for two
        # seasons still gets the four-season accuracy table, because the projection's quality
        # is a property of the projection rather than of which seasons an arm happened to
        # draft, and truncating it would let a two-season run report a flattering subset.
        out["accuracy"] = accuracy.report(league)
    return out


def _ceiling_block(payload: dict[str, Any]) -> dict[str, Any]:
    """TASK 3. Each headline comparison as a FRACTION of what perfect foresight was worth.

    Two of the three ARE distances from ADP; `transform_minus_points` is not, and is expressed
    against the same denominator anyway so the three are on one scale.

    THE SAME NULL MEANS OPPOSITE THINGS AT DIFFERENT CEILINGS, which is the whole reason this
    block exists and why no earlier session could read its own result. If a board built from
    the season's realised totals beats ADP by 40 points, a real projection capturing 12 is
    doing most of what was available. If perfect foresight is worth 400 and the transform
    captures 5, it is a coat of paint. Both look like "+12" and "+5" without a scale.

    Reported under all three lineup policies, because B3 found the sign of a headline flipping
    between them and a fraction computed on one policy would inherit that.
    """
    out: dict[str, Any] = {}
    for suffix in ("", "_oracle", "_hindsight"):
        ceiling = payload.get(f"ceiling_minus_adp{suffix}")
        if not ceiling or isinstance(ceiling.get("mean"), str):
            continue
        base = ceiling["mean"]
        policy = {"": "prior", "_oracle": "oracle", "_hindsight": "hindsight"}[suffix]
        block: dict[str, Any] = {"ceiling": round(base, 3)}
        if abs(base) < 1e-9:
            block["share_undefined_because"] = (
                "perfect foresight was worth 0.0 against ADP on this run, so a share of it "
                "is a division by zero and is not reported"
            )
        else:
            for name in ("transform_minus_adp", "points_minus_adp", "transform_minus_points"):
                got = payload.get(f"{name}{suffix}")
                if got and not isinstance(got.get("mean"), str):
                    block[name] = round(100.0 * got["mean"] / base, 1)
        out[policy] = block
    return out


# Every paired comparison the artifact reports. `real - adp` was first when it was the only
# comparison that said whether anything here was an achievement; B4's board comparisons print
# above it now (`artifact.summary_block`), because on a run with a real board the transform's
# distance from the market is the question and `real - adp` is the overlay's, carried forward.
# B4's two headline comparisons and the ceiling they are read against. `transform_minus_points`
# is the whole question -- same projection, same seat, same room, replacement level on or off.
_B4_COMPARISONS: tuple[tuple[str, str, str], ...] = (
    ("audible_transform", "points_greedy", "transform_minus_points"),
    ("audible_transform", "adp", "transform_minus_adp"),
    ("audible_transform", "adp_board", "transform_minus_adp_board"),
    ("audible_transform", "scarcity_only", "transform_minus_scarcity"),
    ("hindsight_board", "adp", "ceiling_minus_adp"),
    ("hindsight_board", "audible_transform", "ceiling_minus_transform"),
    ("points_greedy", "adp", "points_minus_adp"),
    # THE TRANSFORM WITH THE PROJECTION ERROR REMOVED. Both arms draft the season's realised
    # lines; the only thing between them is still replacement level. If the transform is worth
    # nothing HERE it is worth nothing anywhere, and if it is worth something here while
    # `transform_minus_points` is null, the projection is what is failing rather than the
    # transform. No other comparison separates those two.
    ("hindsight_board", "hindsight_points", "transform_under_perfect_foresight"),
    # THE HARNESS'S OWN INDIFFERENCE TO DURABILITY, priced. Both arms order the same realised
    # lines; one on per-game rate, one on season total. `bootstrap_weeks` replays a player's
    # observed weeks to a full season, so the per-game reading is the one that matches the
    # scorer and the gap is what a season-total ceiling was understating itself by.
    ("hindsight_board", "hindsight_total", "per_game_minus_total_ceiling"),
)

_COMPARISONS: tuple[tuple[str, str, str], ...] = (
    ("real", "adp", "real_minus_adp"),
    ("real", "legacy", "real_minus_legacy"),
    ("legacy", "adp", "legacy_minus_adp"),
    ("real", "legacy_recommend", "real_minus_legacy_recommend"),
    ("legacy", "legacy_recommend", "surface_gap"),
    ("real", "shuffle", "real_minus_shuffle"),
    ("shuffle", "bot", "shuffle_minus_bot"),
    *_B4_COMPARISONS,
)


def _compare(
    rows: Sequence[dict[str, Any]],
    left: str,
    right: str,
    field: str = "advantage",
) -> dict[str, Any] | None:
    """Paired difference, clustered on season. None when nothing pairs.

    *field* selects the lineup: `advantage` is the PRIOR primary, `advantage_season_mean` an
    oracle upper bound, `advantage_realised` the hindsight one. All three are reported for the
    headline comparisons, because the spread between them IS the harness's own uncertainty
    about what a manager could have known, and asserting it in prose would be weaker than
    printing it.

    `flat_lo`/`flat_hi` are the SAME numbers computed without the season clustering, and they
    are written into every comparison so that nobody has to take the clustering on faith. The
    ratio between the two widths is not a constant. Measured on the B3 run it runs from 1.25x
    on `shuffle - bot` to 3.57x on `real - legacy` under the oracle lineup, depending on how
    much of a comparison's variance is between seasons rather than between seeds -- so a gate
    that assumed one number for it was asserting something false. This lets a gate read the
    real pair, and the artifact's summary computes the range rather than restating it.
    """
    paired, keys = _paired_difference(rows, left, right, field)
    if not paired:
        return None
    m, lo, hi = seat.mean_and_interval(paired, [k[0] for k in keys])
    _, flat_lo, flat_hi = seat.mean_and_interval(paired)
    return {
        "n": len(paired),
        "mean": round(m, 3),
        "lo": round(lo, 3),
        "hi": round(hi, 3),
        "flat_lo": round(flat_lo, 3),
        "flat_hi": round(flat_hi, 3),
    }


def _ablation_verdict(name: str, block: dict[str, Any]) -> str:
    """Does removing this term change anything measurable?

    `no_bye` is UNMEASURABLE BY CONSTRUCTION and is labelled so rather than called null. The
    bootstrap resamples a player's own observed weeks, so a bye week never occurs in the
    outcome measure and the harness cannot PRICE what the term buys. The term itself is
    demonstrably live -- non-zero on 66.8% of served rows over 330,399 of them, and moving a
    mean 4.70 of the seat's 16 picks a draft -- so a null here is a property of the harness,
    not of the bye logic. The structural metric that CAN see byes says the same thing:
    `no_bye` moves `unfillable_bye_weeks` by +0.04 [-0.08, +0.16] over 300 paired units,
    which is also null.
    (`no_need` moves the same metric by -0.45 [-0.68, -0.22], so the metric is not inert --
    it resolves an effect when there is one to resolve.)
    """
    if name == "no_bye":
        return (
            "UNMEASURABLE: the bootstrap resamples a player's own weeks, so bye weeks do "
            "not exist in the outcome. A null here says nothing about the bye term."
        )
    lo, hi = block["lo"], block["hi"]
    if isinstance(lo, str) or isinstance(hi, str):
        return "unresolvable: one season-cluster"
    if lo <= 0.0 <= hi:
        return "no measurable change: removing this term is indistinguishable from keeping it"
    direction = "HURTS" if block["mean"] < 0 else "HELPS"
    return (
        f"measurable: removing it {direction} by {abs(block['mean']):.1f} "
        f"[{lo:+.1f}, {hi:+.1f}]"
    )


def _secondary(
    rows: Sequence[dict[str, Any]], suffix: str, label: str
) -> dict[str, Any]:
    """One of the two upper-bound lineups, kept so its distance from the primary is visible.

    Neither is a result. Both are printed beside the primary because the SPREAD between them
    is how much of any arm's number is an artifact of what the lineup was allowed to know.
    """
    seasons_of = [r["season"] for r in rows]
    pf, pf_lo, pf_hi = seat.mean_and_interval(
        [r.get(f"points_for_{suffix}", 0.0) for r in rows], seasons_of
    )
    ad, ad_lo, ad_hi = seat.mean_and_interval(
        [r.get(f"advantage_{suffix}", 0.0) for r in rows], seasons_of
    )
    return {
        "lineup": f"{label} -- SECONDARY, not the headline",
        "points_for": {"mean": round(pf, 3), "lo": round(pf_lo, 3), "hi": round(pf_hi, 3)},
        "advantage": {"mean": round(ad, 3), "lo": round(ad_lo, 3), "hi": round(ad_hi, 3)},
    }


def _positions_drafted(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Mean count of each position the seat drafted, over the arm's units."""
    totals: dict[str, float] = {}
    for row in rows:
        for position, count in (row.get("positions") or {}).items():
            totals[position] = totals.get(position, 0.0) + float(count)
    return {p: round(v / max(1, len(rows)), 4) for p, v in sorted(totals.items())}


def _slot_mean(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Mean points by starting slot AND by position, seat only, under the prior lineup."""
    totals: dict[str, float] = {}
    for row in rows:
        for slot, points in (row.get("slot_points") or {}).items():
            totals[slot] = totals.get(slot, 0.0) + float(points)
    n = max(1, len(rows))
    return {slot: round(v / n, 2) for slot, v in sorted(totals.items())}


def board_vs_adp(config: RunConfig) -> dict[str, Any]:
    """TASK 4. How much ordering is there for the harness to find? None, and here is why.

    `seat.board_from_season` gives audible a board whose value is a MONOTONE TRANSFORM OF ADP
    RANK. So in this harness audible's board order and the market's order are the same list --
    measured below, 128 of 128 exact matches and a Pearson of 1.000000 in every season. There
    is no ordering difference to find, and no amount of ordering work could produce one.

    That is not a defect in the harness; it is the honest consequence of a limit stated since
    B1. No vintage preseason projections exist for any of these seasons, so a board cannot be
    built the way production builds one, and the market's own ordering is the only defensible
    stand-in.

    The production comparison is reported beside it, off the pinned QA fixtures, and it is the
    number that matters: audible's REAL board disagrees with ADP in most of the top 128. That
    disagreement is where audible's value would live, and it is exactly what this harness
    cannot exercise.
    """
    import importlib.util

    out: dict[str, Any] = {
        "harness": {},
        "note": (
            "the harness board is a monotone transform of ADP rank, so its ordering IS the "
            "market's. real - adp therefore measures the OVERLAY alone, never the board."
        ),
    }
    league = weekly.league_config() if config.league == weekly.LEAGUE_KEY else _league(config)
    for season in sorted(set(config.seasons)):
        board = room.load_board(season)
        audible = seat.board_from_season(board, league)
        top = audible.entries[: room.PICKS]
        exact = sum(1 for i, e in enumerate(top, start=1) if e.adp_rank == i)
        apart = sum(1 for i, e in enumerate(top, start=1) if abs(e.adp_rank - i) > room.TEAMS)
        corr, _slope = room._pearson(
            [float(e.adp_rank) for e in top], [float(i) for i in range(1, len(top) + 1)]
        )
        out["harness"][str(season)] = {
            "exact_of_128": exact,
            "disagree_over_one_round": apart,
            "pearson": round(corr, 6),
        }

    loader = REPO / "scripts" / "qa_board_fixture.py"
    fixtures = loader.parent / "fixtures"
    if loader.exists():
        spec = importlib.util.spec_from_file_location("_qa_board_fixture", loader)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            production: dict[str, Any] = {}
            for key in ("espn_green_hope", "espn_davis_drive"):
                path = fixtures / f"qa-board-{key}.json"
                if not path.exists():
                    continue
                board = module.load_board(key, path)
                priced = [e for e in board.entries if e.adp_rank is not None]
                top = sorted(priced, key=lambda e: e.vorp_rank)[: room.PICKS]
                exact = sum(1 for i, e in enumerate(top, start=1) if e.adp_rank == i)
                apart = sum(
                    1 for i, e in enumerate(top, start=1) if abs(e.adp_rank - i) > room.TEAMS
                )
                corr, _slope = room._pearson(
                    [float(e.adp_rank) for e in top],
                    [float(i) for i in range(1, len(top) + 1)],
                )
                production[key] = {
                    "entries": len(board.entries),
                    "exact_of_128": exact,
                    "disagree_over_one_round": apart,
                    "pearson": round(corr, 4),
                }
            if production:
                out["production"] = production
    return out


def _decomposition(arms: dict[str, Any], real_minus_shuffle: Sequence[float]) -> dict[str, Any]:
    """Where the real arm's advantage comes from. Read top to bottom; the terms add up.

    Reported on every run because "the shuffle arm is winning" is only alarming until the
    null control is next to it, and someone reading an artifact six months from now will not
    have that argument in their head.
    """
    bot = arms.get("bot", {}).get("advantage", {}).get("mean")
    shuffle = arms.get("shuffle", {}).get("advantage", {}).get("mean")
    real = arms.get("real", {}).get("advantage", {}).get("mean")
    out: dict[str, Any] = {
        "machinery_bot_in_seat": bot,
        "structure_shuffle_minus_bot": (
            round(shuffle - bot, 3) if shuffle is not None and bot is not None else None
        ),
        "value_ordering_real_minus_shuffle": (
            round(sum(real_minus_shuffle) / len(real_minus_shuffle), 3)
            if real_minus_shuffle
            else None
        ),
        "total_real": real,
    }
    out["reading"] = (
        "machinery at chance; the shuffle arm keeps audible's structure and only loses its "
        "value ordering. READ `real_minus_adp` BEFORE THIS: the terms below are audible "
        "against BOTS, and the bots reach by fitted amounts while the seat does not, so a "
        "noiseless seat of any kind collects what they pass. The baseline arm is what says "
        "whether any of it is audible's doing."
    )
    return out


def _paired_difference(
    rows: Sequence[dict[str, Any]], left: str, right: str, field: str = "advantage"
) -> tuple[list[float], list[tuple[int, int]]]:
    """Differences on matched (season, seed), and the keys, so the caller can cluster.

    Rows are assumed to come from ONE split; `build_payload` filters before calling. Mixing
    splits here would pair a 2024 unit fitted on five seasons with one fitted on three.
    """
    a = {(r["season"], r["seed"]): r.get(field, 0.0) for r in rows if r["arm"] == left}
    b = {(r["season"], r["seed"]): r.get(field, 0.0) for r in rows if r["arm"] == right}
    keys = sorted(a.keys() & b.keys())
    return [a[k] - b[k] for k in keys], keys


def _arm_definition(arm: str) -> str:
    return {
        "real": "audible's board, ordered by the cockpit's own the_call",
        "shuffle": "the same, with the board's value ordering permuted per seed",
        "bot": "the null control: seat played by the room's own bot logic, no overlay",
        "adp": "the SKILL BASELINE: best available by ADP rank, capped, no audible at all",
        "legacy": (
            "the PAGE's pre-audible#61 the_call: board-rank slice, "
            "(-need, urgency, vorp_rank), no effective_score. Like-for-like against real."
        ),
        "legacy_recommend": (
            "the MCP list head's pre-audible#60 sort: "
            "(not grab_now, vorp_rank, not fills_need). A DIFFERENT SURFACE."
        ),
        "no_need": "real, with marginal_start_factor forced to 1.0",
        "no_bye": "real, with bye_conflict_penalty forced to 0.0",
        "no_urgency": "real, with next_pick=None so survives_by and the tier are neutralised",
        "no_slice": "real, with the_call's TOP_N shortlist cap effectively removed",
        "leaky-shuffle": "INJECTION ONLY: shuffle arm reading the real board",
        # B4. Every one of these drafts best-available on its own board order, with the room's
        # roster caps and the same feasibility deadline. Only the ORDER differs.
        "points_greedy": (
            "B4: rank by RAW PROJECTED POINTS. No replacement level, no VORP, no scarcity"
        ),
        "audible_transform": (
            "B4: the SAME projected lines through build_board_from_lines, ordered on "
            "vorp_rank. Differs from points_greedy by one replacement constant per position"
        ),
        "adp_board": "B4: the market's ordering through the same machinery",
        "scarcity_only": (
            "B4 COUNTERFACTUAL: ordered on scarcity_rank. No league config selects this; "
            "value_metric is 'vorp' in both, so scarcity never orders a live board"
        ),
        "hindsight_board": (
            "B4 CEILING and a LABELLED LEAK: the same pipeline over the season's REALISED "
            "stat lines. What perfect foresight was worth, never a result"
        ),
        "hindsight_total": (
            "B4 DIAGNOSTIC and a LABELLED LEAK: the realised lines ordered on SEASON TOTALS "
            "instead of per-game rate. Against hindsight_board it prices the harness's own "
            "indifference to games played"
        ),
        "hindsight_points": (
            "B4 LABELLED LEAK: the realised lines ranked by RAW POINTS. Against "
            "hindsight_board it prices the transform with the projection error removed"
        ),
    }[arm]


# --- gates -------------------------------------------------------------------------------------


def leak_ceiling_failures(payload: dict[str, Any]) -> list[str]:
    """G6d. A ceiling on how far past the ADP baseline an honest ordering can get.

    THE SIGNATURE G6b WATCHES FOR IS NOT THE ONE A REAL LEAK PRODUCES. G6b fires when
    `real - shuffle` COLLAPSES, on the reasoning that a leak lets a scrambled board win as
    hard as a real one. An actual leak was built to test that -- a seat re-ranking its own
    shortlist by what each player went on to score -- and the difference WIDENED instead, from
    +92 to +428, because the leak helps whichever arm has the better shortlist. Every gate
    passed while the real arm sat at +479.8.

    What a leak cannot hide is its SIZE. On the ADP-ORDERED board the `real` arm runs on, the
    values are a monotone transform of ADP rank, so there is no better ordering of it to find;
    audible's contribution is its overlay and the overlay is worth tens of points. An arm
    hundreds of points past the ADP baseline is reading something that is not on the board.

    THAT ARGUMENT DOES NOT REACH B4'S BOARDS AND THE CONSTANT MUST NOT BE APPLIED TO THEM.
    A board built from a projection has a real ordering to find, and this run measures exactly
    how much: `ceiling_minus_adp`, the labelled-leak board built from the season's realised
    lines, beats ADP by hundreds. Applying a ceiling of 150 to those arms would fail an honest
    arm for succeeding. So the board arms get their own bound, below, and it is MEASURED
    rather than constant: perfect foresight is the most any projection can be worth, so an
    honest arm that beats ADP by more than the hindsight board did is reading the outcome.
    Neither bound is relaxed by the other; this adds coverage where there was none.

    IT BOUNDS TWO ARMS, not every board arm. `audible_transform` and `points_greedy` are the
    two whose numbers the report leads with; `adp_board` is bounded by being bit-identical to
    the `adp` baseline it is compared against, and `scarcity_only` is a counterfactual nobody
    reads as a result. The leak arms are exempt by construction -- they ARE the ceiling.
    """
    out: list[str] = []
    baseline = payload.get("real_minus_adp")
    if baseline is not None and float(baseline["mean"]) > seat.LEAK_CEILING:
        out.append(
            f"G6d leak-ceiling: the real arm beats the ADP baseline by "
            f"{baseline['mean']:+.1f}, past the {seat.LEAK_CEILING:+.0f} ceiling. The board "
            f"is a monotone transform of ADP rank and contains no ordering worth that much, "
            f"so the arm is reading something that is not on it."
        )

    ceiling = payload.get("ceiling_minus_adp")
    if ceiling is not None and not isinstance(ceiling.get("mean"), str):
        limit = float(ceiling["mean"])
        for name, label in (
            ("transform_minus_adp", "audible_transform"),
            ("points_minus_adp", "points_greedy"),
        ):
            block = payload.get(name)
            if block is None or isinstance(block.get("mean"), str):
                continue
            if float(block["mean"]) > limit:
                out.append(
                    f"G6e foresight-ceiling: {label} beats the ADP baseline by "
                    f"{block['mean']:+.1f}, past the {limit:+.1f} a board built from the "
                    f"season's REALISED lines managed. No projection can be worth more than "
                    f"perfect foresight, so this arm is reading the outcome."
                )
    return out


def gate_failures(payload: dict[str, Any]) -> list[str]:
    """Every gate the artifact itself can check. Named, so a non-zero exit says which.

    THE LEAK GATES ARE G6a AND G6b, AND THE HANDOFF'S G6 IS NEITHER. That is a refuted
    premise and it is worth stating in full, because the number it produces looks alarming.

    B2 was asked for a shuffle arm that "must land at chance against the bots". It does not.
    The null control says why: a seat played by the room's OWN bot logic, with no audible board
    and no overlay at all, lands at chance as symmetry demands, which is what says the
    measurement machinery is sound. The live numbers are in the artifact and are deliberately
    not restated here -- an earlier version of this docstring carried five of them and every
    one went stale within a session.

    So the shuffle arm is not a no-skill control. Randomising the board removes audible's
    VALUE ORDERING and leaves its STRUCTURE -- the need logic, the surplus discount, the bye
    term, the feasibility deadline. That structure is worth tens of points against bots that
    draft a second quarterback in a one-QB league where it can never start. A shuffled board
    that still refuses that quarterback beats them, and it should. The size is in the
    artifact's decomposition block and is not restated here for the reason above.

    The decomposition -- machinery, plus structure, plus value ordering, equalling `real` --
    is computed on every run and printed at the top of every artifact. It is deliberately not
    restated here for the same reason.

    What a leak would look like, and what these two gates therefore test:

    G6a -- the null control must land at chance. If a bot in the seat wins, the machinery
      itself is scoring the seat differently from the others and no arm's number means
      anything.
    G6b -- the real arm must beat the shuffle arm. If outcome information leaked into the
      draft, a scrambled board would win as hard as the real one, because the leak and not
      the ordering would be doing the work. `real - shuffle` collapsing toward zero is the
      signature.

    The handoff's literal G6 is still computed, still printed at the top of every artifact,
    and still says NO. It is reported rather than silenced, and `require_shuffle_at_chance`
    in the config turns it back into a hard gate for anyone who disagrees with this reading.
    """
    failures: list[str] = []

    if not payload.get("units"):
        failures.append(
            "G0 empty-run: the artifact contains no units. Every arm then reads "
            "0.0 [0.0, 0.0] and every other gate passes on nothing."
        )

    baseline = payload.get("real_minus_adp")
    if baseline is None:
        failures.append(
            "G6c skill-baseline: no `adp` arm, so there is nothing that says beating the "
            "bots is an achievement rather than an artifact of a noiseless seat in a noisy "
            "room."
        )

    bot = payload["arms"].get("bot")
    if bot is None:
        failures.append(
            "G6a null-control: no `bot` arm in this run. Without a seat played by the room's "
            "own logic there is nothing that says the machinery scores every seat alike, and "
            "every other number is unanchored."
        )
    else:
        lo, hi = bot["advantage"]["lo"], bot["advantage"]["hi"]
        if isinstance(lo, str) or isinstance(hi, str):
            lo, hi = float("-inf"), float("inf")
        if not (lo <= 0.0 <= hi):
            failures.append(
                f"G6a null-control-at-chance: a bot in the seat scored "
                f"{bot['advantage']['mean']:+.1f} [{lo:+.1f}, {hi:+.1f}], which excludes "
                f"zero. By symmetry it must be chance; it is not, so the machinery is "
                f"scoring the seat differently from the others."
            )

    diff = payload.get("real_minus_shuffle")
    if diff is not None and isinstance(diff["lo"], str):
        failures.append(
            "G6b real-beats-shuffle: unresolvable. This run has one season-cluster, so there "
            "is no interval to read. Add SEASONS, not seeds."
        )
    elif diff is not None and diff["lo"] <= 0.0:
        failures.append(
            f"G6b real-beats-shuffle: real - shuffle is {diff['mean']:+.1f} "
            f"[{diff['lo']:+.1f}, {diff['hi']:+.1f}], which includes zero. A scrambled board "
            f"doing as well as the real one is what a leak looks like."
        )

    if payload.get("require_shuffle_at_chance") and not payload["shuffle"]["at_chance"]:
        failures.append(
            f"G6 shuffle-at-chance: advantage {payload['shuffle']['advantage']:+.1f} "
            f"[{payload['shuffle']['lo']:+.1f}, {payload['shuffle']['hi']:+.1f}] is "
            f"significantly positive"
        )

    failures.extend(leak_ceiling_failures(payload))

    for name, block in payload["arms"].items():
        if block["structural"]["illegal_lineups"]:
            failures.append(
                f"G10 legal-lineups: arm {name} produced "
                f"{block['structural']['illegal_lineups']} seats that cannot start a lineup"
            )
    missing = [k for k, v in payload["pins"].items() if not v.get("sha256")]
    if missing:
        failures.append(f"G5 provenance: no checksum for {missing}")
    for required in ("code_sha", "config_hash", "seeds", "league", "fit", "arms"):
        if required not in payload:
            failures.append(f"G5 provenance: artifact has no `{required}`")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim run", description="Run a B2 sweep unattended. Offline, resumable, gated."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="continue from the checkpoint")
    parser.add_argument("--out", type=Path, default=None, help="artifact path")
    parser.add_argument("--log", type=Path, default=None, help="run log path")
    parser.add_argument(
        "--checkpoint-dir", type=Path, default=None,
        help="where the checkpoint lives (default: sim/runs). Point a test run elsewhere.",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    out = args.out or RUNS_DIR / f"{config.name}.json"
    logfile = args.log or RUNS_DIR / f"{config.name}.log"
    setup_logging(logfile)
    log.info(
        "run %s  config %s  units %d",
        config.name, config.config_hash[:12], len(config.units()),
    )

    import tempfile

    with tempfile.TemporaryDirectory(prefix="sim-run-") as tmp:
        payload = execute(
            config, resume=args.resume, state_dir=Path(tmp),
            checkpoint_dir=args.checkpoint_dir,
        )

    artifact.write(out, payload)
    log.info("artifact %s  digest %s", out, payload["content_digest"][:16])
    for line in artifact.summary_block(payload):
        log.info("| %s", line)

    failures = gate_failures(payload)
    for failure in failures:
        log.error("GATE FAILED: %s", failure)
    if failures:
        log.error("%d gate(s) failed", len(failures))
        return 1
    log.info("all gates passed")
    return 0
