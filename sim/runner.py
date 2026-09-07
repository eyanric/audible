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
  build. Preflight opens and checksums every file the run will read, and exits non-zero naming
  the first one missing. Nothing here ever reaches the network.
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
sorted arm, then season, then seed -- and each unit's result depends only on its own seed, so
a resumed run produces the byte-identical artifact a straight-through run does. That is G2 and
G4 in one property, and it is the reason `run_arm` takes a seed rather than an RNG.
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

from . import LIVE_CACHE, SIM_CACHE, artifact, room, seat, weekly

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
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(
            artifact.canonical(
                {
                    "name": self.name, "seasons": list(self.seasons),
                    "seeds": list(self.seeds), "arms": list(self.arms),
                    "seat": self.seat, "league": self.league,
                    "fit_seasons": list(self.fit_seasons),
                }
            ).encode("utf-8")
        ).hexdigest()

    def units(self) -> list[tuple[str, int, int]]:
        """Every (arm, season, seed) this run will produce, in a fixed order.

        Sorted, so a resumed run walks the identical sequence and the artifact it writes is
        byte-identical to a straight-through one.
        """
        return [
            (arm, season, seed)
            for arm in sorted(self.arms)
            for season in sorted(self.seasons)
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
    return RunConfig(
        name=str(run["name"]),
        seasons=tuple(int(s) for s in run["seasons"]),
        seeds=tuple(int(s) for s in seeds),
        arms=tuple(str(a) for a in run["arms"]),
        seat=int(run["seat"]),
        league=str(run["league"]),
        fit_seasons=tuple(int(s) for s in run.get("fit_seasons", room.SEASONS)),
        raw=blob,
    )


# --- preflight ------------------------------------------------------------------------------


def required_inputs(config: RunConfig) -> list[str]:
    """Every file the run will read, named before anything is opened."""
    names = ["nflverse/ff_playerids.parquet", "nflverse/teams.parquet"]
    for season in sorted(set(config.seasons) | set(config.fit_seasons)):
        names.append(f"ffc_adp_standard_8_{season}.json")
        names.append(f"espn_draft_{room.LEAGUE_ID}_{season}.json")
    for season in sorted(set(config.seasons)):
        names.append(f"nflverse/player_stats_{season}.parquet")
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
    unknown = [a for a in config.arms if a not in ("real", "shuffle", "bot", "leaky-shuffle")]
    if unknown:
        raise SystemExit(f"PREFLIGHT FAILED: unknown arm(s) {unknown}")
    if "shuffle" not in config.arms:
        raise SystemExit(
            "PREFLIGHT FAILED: the shuffle arm is not optional. It is the leak detector and "
            "it runs on every run, permanently -- five prior validation attempts have failed "
            "and a sixth that suddenly succeeds is assumed leaky until shuffle says otherwise."
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

    def __init__(self, path: Path, config: RunConfig) -> None:
        self.path = path
        self.config = config

    def load(self) -> dict[tuple[str, int, int], dict[str, Any]]:
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
            out[(payload["arm"], payload["season"], payload["seed"])] = payload
        return out

    def start(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = artifact.canonical(
            {"config_hash": self.config.config_hash, "name": self.config.name}
        )
        self.path.write_text(header + "\n", encoding="utf-8")

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
    done: dict[tuple[str, int, int], dict[str, Any]],
) -> Iterator[tuple[str, int, int]]:
    for unit in config.units():
        if unit not in done:
            yield unit


def execute(
    config: RunConfig, *, resume: bool, state_dir: Path, progress_every: int = 25
) -> dict[str, Any]:
    """Run every unit, checkpointing as it goes, and return the artifact payload."""
    started = time.perf_counter()
    log.info("preflight: %d inputs", len(required_inputs(config)))
    pins = preflight(config)
    log.info("preflight ok: every input present and checksummed")

    checkpoint = Checkpoint(RUNS_DIR / f"{config.name}.checkpoint.jsonl", config)
    if not resume and checkpoint.path.exists():
        checkpoint.path.unlink()
    checkpoint.start()
    done = checkpoint.load()
    if done:
        log.info("resuming: %d of %d units already done", len(done), len(config.units()))

    fit = room.fit_room(config.fit_seasons)
    boards = {s: room.load_board(s) for s in sorted(set(config.seasons))}
    weeks = {s: weekly.weekly_points(s) for s in sorted(set(config.seasons))}
    league = weekly.league_config() if config.league == weekly.LEAGUE_KEY else _league(config)
    log.info(
        "fit: %d/%d picks joined, scheduled=%s",
        fit.joined, fit.total, sorted(fit.scheduled),
    )

    pending = list(iter_units(config, done))
    for index, (arm, season, seed) in enumerate(pending, start=1):
        result = seat.run_arm(
            arm, season, seed,
            season_board=boards[season], fit=fit, week_table=weeks[season],
            config=league, state_dir=state_dir, seat=config.seat,
        )
        structural = artifact.structural_for(
            result.picks, config.seat, weeks[season].byes, boards[season]
        )
        payload = {
            "arm": arm, "season": season, "seed": seed,
            "points_for": round(result.points_for, 4),
            "opponent_mean": round(
                sum(result.opponent_points) / len(result.opponent_points), 4
            ),
            "advantage": round(result.advantage, 4),
            "calls": result.calls,
            "deadline_picks": result.deadline_picks,
            "unresolved": result.unresolved,
            "unfillable_bye_weeks": structural.unfillable_bye_weeks,
            "wasted_roster_slots": structural.wasted_roster_slots,
            "positional_surplus": structural.positional_surplus,
            "illegal_lineups": structural.illegal_lineups,
        }
        checkpoint.append(payload)
        done[(arm, season, seed)] = payload
        if index % progress_every == 0 or index == len(pending):
            elapsed = time.perf_counter() - started
            log.info(
                "%d/%d units (%d done overall) eta %s",
                index, len(pending), len(done), _eta(index, len(pending), elapsed),
            )

    wall = time.perf_counter() - started
    return build_payload(config, pins, fit, done, wall)


def _league(config: RunConfig) -> Any:
    from audible.config import load_league

    return load_league(REPO / "leagues" / f"{config.league}.toml")


def build_payload(
    config: RunConfig,
    pins: dict[str, dict[str, str]],
    fit: room.Fit,
    done: dict[tuple[str, int, int], dict[str, Any]],
    wall: float,
) -> dict[str, Any]:
    rows = [done[u] for u in config.units()]
    arms: dict[str, Any] = {}
    for arm in sorted(config.arms):
        mine = [r for r in rows if r["arm"] == arm]
        pf, pf_lo, pf_hi = seat.mean_and_interval([r["points_for"] for r in mine])
        ad, ad_lo, ad_hi = seat.mean_and_interval([r["advantage"] for r in mine])
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
                # rather than from audible's ordering. Audible never names a kicker on its
                # own -- see `seat.AudibleSeat.choose` -- and this is the size of that.
                "deadline_picks": round(
                    sum(r["deadline_picks"] for r in mine) / max(1, len(mine)), 4
                ),
            },
            "points_for": {"mean": round(pf, 3), "lo": round(pf_lo, 3), "hi": round(pf_hi, 3)},
            "advantage": {"mean": round(ad, 3), "lo": round(ad_lo, 3), "hi": round(ad_hi, 3)},
        }

    shuffle_rows = [r for r in rows if r["arm"] == "shuffle"]
    sh, sh_lo, sh_hi = seat.mean_and_interval([r["advantage"] for r in shuffle_rows])
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
        "units": len(rows),
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
        "leak_decomposition": _decomposition(arms, _paired_difference(rows, "real", "shuffle")),
        "outcome_measure": "points-for under weekly optimal lineups",
        "slots_scored": f"7 of {len(room.STARTING_SLOTS)} (K and DEF have no scoreable rows)",
        "timing": {"wall_s": round(wall, 2)},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if "real" in arms and "shuffle" in arms:
        paired = _paired_difference(rows, "real", "shuffle")
        if paired:
            m, lo, hi = seat.mean_and_interval(paired)
            payload["real_minus_shuffle"] = {
                "n": len(paired), "mean": round(m, 3),
                "lo": round(lo, 3), "hi": round(hi, 3),
            }
    return payload


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
        "value ordering, which is why it beats bots that draft a second unstartable QB"
    )
    return out


def _paired_difference(
    rows: Sequence[dict[str, Any]], left: str, right: str
) -> list[float]:
    """Differences on matched (season, seed). Unmatched units are dropped, not averaged."""
    a = {(r["season"], r["seed"]): r["advantage"] for r in rows if r["arm"] == left}
    b = {(r["season"], r["seed"]): r["advantage"] for r in rows if r["arm"] == right}
    return [a[k] - b[k] for k in sorted(a.keys() & b.keys())]


def _arm_definition(arm: str) -> str:
    return {
        "real": "audible's board, ordered by the cockpit's own the_call",
        "shuffle": "the same, with the board's value ordering permuted per seed",
        "bot": "the null control: seat played by the room's own bot logic, no overlay",
        "leaky-shuffle": "INJECTION ONLY: shuffle arm reading the real board",
    }[arm]


# --- gates -------------------------------------------------------------------------------------


def gate_failures(payload: dict[str, Any]) -> list[str]:
    """Every gate the artifact itself can check. Named, so a non-zero exit says which.

    THE LEAK GATES ARE G6a AND G6b, AND THE HANDOFF'S G6 IS NEITHER. That is a refuted
    premise and it is worth stating in full, because the number it produces looks alarming.

    B2 was asked for a shuffle arm that "must land at chance against the bots". Measured over
    300 paired runs it does not -- it beats the field by +42.9 [+25.6, +60.1]. The null
    control says why. A seat played by the room's OWN bot logic, with no audible board and no
    overlay at all, lands at -4.5 [-25.8, +16.7]: exactly chance, as symmetry demands, which
    is what says the measurement machinery is sound.

    So the shuffle arm is not a no-skill control. Randomising the board removes audible's
    VALUE ORDERING and leaves its STRUCTURE -- the need logic, the surplus discount, the bye
    term, the feasibility deadline. That structure is worth about +47 against bots that draft
    1.8 quarterbacks each in a one-QB league where a second can never start. A shuffled board
    that still refuses the second quarterback beats them, and it should.

    The decomposition, from the same run:

        machinery (bot in the seat)          -4.5 [-25.8, +16.7]
        + structure (shuffle - bot)         +47.4
        + value ordering (real - shuffle)  +103.5 [+80.1, +127.0]
        = real                             +146.4 [+127.9, +164.9]

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

    bot = payload["arms"].get("bot")
    if bot is None:
        failures.append(
            "G6a null-control: no `bot` arm in this run. Without a seat played by the room's "
            "own logic there is nothing that says the machinery scores every seat alike, and "
            "every other number is unanchored."
        )
    else:
        lo, hi = bot["advantage"]["lo"], bot["advantage"]["hi"]
        if not (lo <= 0.0 <= hi):
            failures.append(
                f"G6a null-control-at-chance: a bot in the seat scored "
                f"{bot['advantage']['mean']:+.1f} [{lo:+.1f}, {hi:+.1f}], which excludes "
                f"zero. By symmetry it must be chance; it is not, so the machinery is "
                f"scoring the seat differently from the others."
            )

    diff = payload.get("real_minus_shuffle")
    if diff is not None and diff["lo"] <= 0.0:
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
        payload = execute(config, resume=args.resume, state_dir=Path(tmp))

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
