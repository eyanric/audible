"""TASK B2/2 -- the run artifact. One file per run, fixed schema, committed.

Runs then diff in git, and a number that moves can be attributed rather than argued about.

WHY PROVENANCE IS THE POINT
----------------------------
Without it you cannot tell whether a number moved because the ordering changed or because a
parquet did, and that is not hypothetical here. `schedules_2026` was measured re-fetching to a
different sha256 because eight betting-odds columns had changed upstream, and a DynastyProcess
URL began returning an HTML 404 page on 2026-08-17 while every caller kept treating it as
data. Either would move a result silently.

So every artifact carries the code SHA, the config hash, a sha256 for every pinned input it
read, the seed set, the league config, the arm definitions, the wall clock, and the room's
fitted parameters. A missing pin checksum is a failed gate, not a warning.

READING ORDER, and it is deliberate
------------------------------------
1. STRUCTURAL outcomes. Unfillable bye weeks, wasted roster slots, positional distribution
   against startable slots. These have known-correct directions -- nobody has to decide
   whether fewer unfillable weeks is better -- so they are actionable without interpretation
   and they come first.
2. POINTS, with an interval. Never a bare point estimate.
3. THE SHUFFLE ARM, always, on every run. It is the leak detector and it is worth nothing if
   it is only consulted when a result looks surprising.

DETERMINISM
-----------
`content_digest` covers everything except `timing` and `generated_at`. Same config, same
digest, byte for byte -- which is what G4 checks, and what makes two artifacts in git
comparable by eye.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import room, seat

SCHEMA_VERSION: int = 1

# Fields excluded from the content digest. Wall clock is the only thing about a run that is
# allowed to differ between two runs of the same config, and `generated_at` is wall clock by
# another name. Everything else being in the digest is what makes G4 a real gate.
VOLATILE: frozenset[str] = frozenset({"timing", "generated_at"})


def code_sha() -> str:
    """The commit the run was made from, plus a dirty marker. Never raises."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}"
    except Exception:  # noqa: BLE001 -- a run outside a checkout still gets an artifact
        return "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(payload: Any) -> str:
    """Stable JSON. Sorted keys, no incidental whitespace, no NaN or Infinity.

    `Fit.supply_ratio["K"]` is `float("inf")` -- the board holds zero kickers inside the top
    128 in every season -- and `json.dumps` would happily emit a bare `Infinity`, which is not
    JSON and which no other reader will accept. It is written as the string "inf" instead.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _clean(value: Any) -> Any:
    """Make a value JSON-safe without hiding what it was."""
    if isinstance(value, float):
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
        if value != value:  # NaN
            return "nan"
        return round(value, 6)
    if isinstance(value, frozenset | set):
        return sorted(_clean(v) for v in value)
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, tuple | list):
        return [_clean(v) for v in value]
    return value


def fit_block(fit: room.Fit) -> dict[str, Any]:
    """Every fitted parameter, so a run can be reproduced from its own artifact."""
    return _clean(
        {
            "seasons": fit.seasons,
            "joined": fit.joined,
            "total": fit.total,
            "scheduled": fit.scheduled,
            # THE CLASSIFIER THAT DECIDED `scheduled`, so `runner.gate_failures` can name the
            # disagreeing position and a reader can check the verdict without refitting.
            "clock_ratio": fit.clock_ratio,
            "clock_sd_pick": fit.clock_sd_pick,
            "clock_sd_resid": fit.clock_sd_resid,
            "clock_n": fit.clock_n,
            "clock_unclassified": fit.clock_unclassified,
            "clock_resolvable": fit.clock_resolvable,
            # Diagnostic from B9 on; it decides nothing. See room.SUPPLY_RATIO_CUT.
            "supply_ratio": fit.supply_ratio,
            "supply_avail": fit.supply_avail,
            "supply_drafted": fit.supply_drafted,
            "mu": fit.mu,
            "sigma": fit.sigma,
            "cell_n": fit.cell_n,
            "pooled": fit.pooled,
            "pick_mu": fit.pick_mu,
            "pick_sd": fit.pick_sd,
            "caps": fit.caps,
            "cap_hist": {k: {str(n): c for n, c in v.items()} for k, v in fit.cap_hist.items()},
            "round_sigma": fit.round_sigma,
            "second_specialist_p": fit.second_specialist_p,
            "offboard_per_draft": fit.offboard_per_draft,
            "offboard_cells": [list(c) for c in fit.offboard_cells],
            "season_sigma": {str(k): v for k, v in fit.season_sigma.items()},
            "season_sigma_mean": fit.season_sigma_mean,
            "season_sigma_tau": fit.season_sigma_tau,
        }
    )


@dataclass(frozen=True, slots=True)
class Structural:
    """The outcomes with known-correct directions. Lower is better for every field."""

    unfillable_bye_weeks: float
    wasted_roster_slots: float
    positional_surplus: float
    illegal_lineups: int


def structural_for(
    picks: Sequence[Any], seat: int, byes: Mapping[str, int], board: room.SeasonBoard
) -> Structural:
    """Structural quality of one seat's roster. Every number is a count, not a taste.

    unfillable_bye_weeks -- regular-season weeks where the roster cannot fill every starting
        slot, because too many of its eligible players share that bye. This is the failure
        `docs/STATE.md` describes: two running backs on the same bye and two dedicated RB
        slots means one week with no legal lineup, and no flex can rescue it.

        Filled greedily, most-specific-slot-first, which is optimal for THIS eligibility
        lattice and was checked by brute force against a true max-matching over every roster of
        length <= 9 and 300,000 random longer ones: zero disagreements. It stops being optimal
        the moment a SUPER_FLEX or a second overlapping flex appears, which is the same caveat
        `weekly.optimal_week` carries and the reason that one is exact.

        NOTE that this metric cannot influence `points_for`: the bootstrap resamples a player's
        own observed weeks, so bye weeks do not exist in the outcome measure. It is reported
        because it is a real property of a roster, not because it feeds anything.
    wasted_roster_slots -- surplus at a position that can fill AT MOST ONE starting slot, so
        D/ST, K and QB in this league. A second kicker is dead weight in a way a fifth receiver
        is not, because the receiver can still flex. This is deliberately narrower than
        `positional_surplus` and the two are reported side by side.
    positional_surplus -- total players held beyond startable capacity, summed over EVERY
        position. A fourth tight end counts here and not above.
    """
    by_rank = {r.rank: r for r in board.rows}
    roster: list[tuple[str, int | None]] = []
    for pick in picks:
        if pick.seat != seat:
            continue
        row = by_rank.get(pick.rank) if not pick.offboard else None
        team = row.team if row is not None else None
        roster.append((pick.position, byes.get(team) if team else None))

    counts: dict[str, int] = {}
    for position, _bye in roster:
        counts[position] = counts.get(position, 0) + 1

    startable: dict[str, int] = {}
    for slot in room.STARTING_SLOTS:
        for position in room.SLOT_ELIGIBILITY[slot]:
            startable[position] = startable.get(position, 0) + 1

    unfillable = 0
    for week in range(1, 19):
        available = [(f"p{i}", pos) for i, (pos, bye) in enumerate(roster) if bye != week]
        filled = 0
        used: set[str] = set()
        for slot in room.STARTING_SLOTS:
            allowed = set(room.SLOT_ELIGIBILITY[slot])
            hit = next(
                (key for key, pos in available if key not in used and pos in allowed), None
            )
            if hit is not None:
                used.add(hit)
                filled += 1
        if filled < len(room.STARTING_SLOTS):
            unfillable += 1

    wasted = sum(
        max(0, n - startable.get(position, 0))
        for position, n in counts.items()
        if startable.get(position, 0) <= 1
    )
    surplus = sum(max(0, n - startable.get(position, 0)) for position, n in counts.items())

    filled_slots = room._Roster()
    for position, _bye in roster:
        filled_slots.add(position)

    return Structural(
        unfillable_bye_weeks=float(unfillable),
        wasted_roster_slots=float(wasted),
        positional_surplus=float(surplus),
        illegal_lineups=1 if filled_slots.unfilled() else 0,
    )


def wrap60(text: str, indent: str = "  ") -> list[str]:
    """Hard-wrap so the FINISHED line is at most 60 characters.

    58, not 60: `write` prepends "# " to every summary line, and wrapping at 60 put four
    lines of the committed artifacts at 61 and 62 columns. The budget belongs to the reader,
    not to the text before the prefix is added.
    """
    lines: list[str] = []
    current = indent
    for word in text.split():
        if len(current) + len(word) > 58 and current.strip():
            lines.append(current.rstrip())
            current = f"{indent}{word} "
        else:
            current = f"{current}{word} "
    if current.strip():
        lines.append(current.rstrip())
    return lines


def _interval(block: Mapping[str, Any]) -> str:
    """`mean [lo, hi]`, or `mean [unresolvable]` when the run has one season-cluster.

    `_clean` turns an infinity into the string "inf", so an unresolvable bound arrives here as
    text rather than a float. Formatting it with `:+.1f` is how this crashed.
    """
    lo, hi = block["lo"], block["hi"]
    if isinstance(lo, str) or isinstance(hi, str):
        return f"{float(block['mean']):+.1f} [unresolvable: one season]"
    return f"{float(block['mean']):+.1f} [{lo:+.1f}, {hi:+.1f}]"


def summary_block(payload: Mapping[str, Any]) -> list[str]:
    """The mobile-readable block that heads every artifact. key: value, wrapped at 60.

    Reading order is deliberate and it starts with the two things a reader must not miss: the
    lineup measure in use, and whether audible beats the ADP baseline. Everything else is
    detail underneath those.
    """
    arms = payload["arms"]
    shuffle = payload["shuffle"]
    out: list[str] = [
        f"run: {payload['run']}",
        f"seasons: {', '.join(str(s) for s in payload['seasons'])}",
        f"seeds: {payload['seed_count']}  seat: {payload['seat']}",
        f"units: {payload['units']}  wall: {payload['timing']['wall_s']:.1f}s",
        "",
        "OUTCOME MEASURE:",
    ]
    out.extend(wrap60(str(payload.get("outcome_measure", "?"))))
    # COMPUTED from the arms, for the same reason the clustering ratio below is: a hardcoded
    # "+96 to +115" was carried here and there is no reason for a number this file can read.
    gaps = [
        block["oracle_secondary"]["points_for"]["mean"] - block["points_for"]["mean"]
        for block in (payload.get("arms") or {}).values()
        if isinstance(block, Mapping) and "oracle_secondary" in block
    ]
    hind = [
        block["realised_secondary"]["points_for"]["mean"] - block["points_for"]["mean"]
        for block in (payload.get("arms") or {}).values()
        if isinstance(block, Mapping) and "realised_secondary" in block
    ]
    if gaps and hind:
        out.extend(
            wrap60(
                f"TWO UPPER BOUNDS are printed beside every comparison. "
                f"An `oracle` lineup chosen on each player's own season "
                f"mean is worth +{min(gaps):.0f} to +{max(gaps):.0f} "
                f"points a season over the prior; a `hindsight` lineup "
                f"chosen weekly is worth +{min(hind):.0f} to "
                f"+{max(hind):.0f}. Any effect smaller than that spread "
                f"is inside the harness's own uncertainty about what a "
                f"manager could have known, and is not a result."
            )
        )

    out.append("")
    if "real_minus_adp" in payload:
        d = payload["real_minus_adp"]
        beats = not isinstance(d["lo"], str) and d["lo"] > 0.0
        out.append("THE BASELINE, and read this before anything else:")
        out.extend(
            wrap60(
                "audible against a ten-line ADP-greedy seat with no "
                f"audible in it at all, paired: {_interval(d)}."
            )
        )
        out.extend(
            wrap60(
                "audible beats the obvious alternative."
                if beats
                else "audible does NOT beat the obvious alternative."
            )
        )

    board = payload.get("board_vs_adp") or {}
    if board:
        out.append("")
        # SCOPED TO THE ARMS THAT RUN ON IT. This block describes `seat.board_from_season`,
        # which is what `real`, `shuffle`, `legacy`, `legacy_recommend`, `leaky-shuffle` and
        # the four ablations draft off -- every arm routed through `build_seat`. B4's board
        # arms build their own board from a projection and are compared to ADP separately,
        # below; saying "none" over the whole artifact would now be false.
        out.append("HOW MUCH ORDERING IS THERE ON THE ADP-ORDERED BOARD")
        out.append("that real/shuffle/legacy/the ablations draft off? none:")
        for season, row in sorted((board.get("harness") or {}).items()):
            out.append(
                f"  {season}: {row['exact_of_128']}/128 exact, "
                f"{row['disagree_over_one_round']} disagree >1rd, r={row['pearson']}"
            )
        out.extend(wrap60(str(board.get("note", ""))))
        if payload.get("projection"):
            out.extend(
                wrap60(
                    "B4's board arms are NOT on that board and their own "
                    "agreement with ADP is reported below. Nothing in "
                    "this paragraph applies to them."
                )
            )
        for key, row in sorted((board.get("production") or {}).items()):
            out.append(f"  production {key}:")
            out.append(
                f"    {row['exact_of_128']}/128 exact, "
                f"{row['disagree_over_one_round']} disagree >1rd, r={row['pearson']}"
            )
        if board.get("production"):
            out.extend(
                wrap60(
                    "the production board disagrees with ADP across most "
                    "of the top 128. That disagreement is where audible's "
                    "value would live and this harness cannot exercise it."
                )
            )

    out.append("")
    out.append("advantage over the field, paired, clustered on season:")
    for name in sorted(arms):
        out.append(f"  {name:<11s} {_interval(arms[name]['advantage'])}")

    out.append("")
    if payload.get("projection"):
        out.extend(_b4_block(payload))

    out.append("paired comparisons. PRIOR is primary; the lines")
    out.append("under each say what an oracle lineup would have paid:")
    for label, key in (
        ("transform - points", "transform_minus_points"),
        ("transform - adp", "transform_minus_adp"),
        ("transform - scarcity", "transform_minus_scarcity"),
        ("points - adp", "points_minus_adp"),
        ("CEILING - adp", "ceiling_minus_adp"),
        ("CEILING - transform", "ceiling_minus_transform"),
        ("real - adp", "real_minus_adp"),
        ("real - legacy", "real_minus_legacy"),
        ("legacy - adp", "legacy_minus_adp"),
        ("real - legacy_rec", "real_minus_legacy_recommend"),
        ("surface gap", "surface_gap"),
        ("real - shuffle", "real_minus_shuffle"),
        ("shuffle - bot", "shuffle_minus_bot"),
    ):
        if key in payload:
            out.append(f"  {label}: {_interval(payload[key])}")
            for name, suffix in (("oracle", "_oracle"), ("hindsight", "_hindsight")):
                got = payload.get(f"{key}{suffix}")
                if got:
                    out.append(f"    {name}: {_interval(got)}")

    if payload.get("ablations"):
        out.append("")
        out.append("ablations, each vs real (negative = removing it HURTS):")
        for name, block in sorted(payload["ablations"].items()):
            out.append(f"  {name:<11s} {_interval(block)}")
            out.extend(wrap60(str(block.get("verdict", "")), indent="    "))

    out.append("")
    out.append("points by POSITION, seat only, prior lineup. Read this")
    out.append("and not a by-slot table: RB and WR each name TWO")
    out.append("starting slots, and a surplus TE started at FLEX lands")
    out.append("in the FLEX bucket, so by-slot cannot see hoarding.")
    for name in sorted(arms):
        slots = arms[name].get("slot_points") or {}
        by_position = {k[4:]: v for k, v in slots.items() if k.startswith("pos:")}
        total = sum(by_position.values()) or 1.0
        parts = " ".join(
            f"{position}:{points / total * 100:.0f}%"
            for position, points in sorted(by_position.items())
        )
        out.append(f"  {name:<17s} {parts}")

    if any(block.get("positions_drafted") for block in arms.values()):
        out.append("")
        out.append("WHAT EACH ARM DRAFTS, mean of 16 picks. This is the")
        out.append("mechanism behind every board comparison above:")
        for name in sorted(arms):
            counts = arms[name].get("positions_drafted") or {}
            parts = " ".join(f"{p}:{v:.2f}" for p, v in sorted(counts.items()) if v)
            out.append(f"  {name:<18s} {parts}")

    if payload.get("walk_forward"):
        out.append("")
        out.append("WALK-FORWARD, fit and test shown side by side:")
        for label in ("wf-in", "wf-out"):
            block = payload["walk_forward"].get(label)
            if not block:
                continue
            seasons = block.get("seasons", [])
            out.append(f"  {label} ({', '.join(str(x) for x in seasons)}):")
            for key in ("real_minus_adp", "real_minus_legacy", "real_minus_shuffle"):
                if key in block:
                    out.append(f"    {key:<19s}{_interval(block[key])}")
            if len(seasons) < 3:
                out.extend(
                    wrap60(
                        f"{label} has {len(seasons)} season-clusters, so "
                        f"{max(0, len(seasons) - 1)} degrees of freedom and a t "
                        f"quantile of {seat._t95(len(seasons) - 1):.3g}. Those "
                        "intervals are too wide to resolve anything and are "
                        "printed as a limit, not as a result. "
                        f"{len(payload.get('seasons') or ())} seasons cannot "
                        "be split any better.",
                        indent="    ",
                    )
                )
        out.extend(
            wrap60(
                "an effect present in-sample and absent out-of-sample is "
                "the signature of overfitting. Both are printed so nobody "
                "has to remember to look."
            )
        )

    out.append("")
    out.append("structural (lower is better):")
    for name in sorted(arms):
        st = arms[name]["structural"]
        out.append(
            f"  {name:<11s} bye {st['unfillable_bye_weeks']:.2f}  "
            f"wasted {st['wasted_roster_slots']:.2f}  "
            f"surplus {st['positional_surplus']:.2f}"
        )
        out.append(
            f"              illegal {st['illegal_lineups']}  "
            f"deadline/16 {st['deadline_picks']:.2f}"
        )

    if payload.get("leak_decomposition"):
        d = payload["leak_decomposition"]
        out.append("")
        out.append("where the advantage over the BOTS comes from:")
        out.append(f"  machinery (bot in seat): {d['machinery_bot_in_seat']:+.1f}")
        out.append(f"  + structure:             {d['structure_shuffle_minus_bot']:+.1f}")
        out.append(f"  + value ordering:        {d['value_ordering_real_minus_shuffle']:+.1f}")
        out.append(f"  = real:                  {d['total_real']:+.1f}")

    out.append("")
    out.append("shuffle control (the leak detector):")
    out.append(f"  at chance: {'yes' if shuffle['at_chance'] else 'NO'}")
    band = {"mean": shuffle["advantage"], "lo": shuffle["lo"], "hi": shuffle["hi"]}
    out.append(f"  advantage: {_interval(band)}")
    out.extend(wrap60(shuffle["reading"], indent="  "))
    if not shuffle["at_chance"]:
        out.extend(
            wrap60(
                "READ THE DECOMPOSITION ABOVE. The null control -- a bot "
                "in the same seat -- lands at chance, so the machinery is "
                "sound. The shuffle arm keeps audible's STRUCTURE and only "
                "loses its value ordering, so it is not a no-skill control "
                "and beating bots that draft a second unstartable QB is "
                "not a leak. The leak gates are the null control, "
                "real-beats-shuffle, and the G6d size ceiling."
            )
        )

    out.append("")
    out.append("intervals are clustered on SEASON, not on seed:")
    # COMPUTED, never written down. Every previous version of this line carried a hardcoded
    # ratio and every one of them went stale -- the last said "2.5 to 2.9 times", which no
    # comparison on the run reaches. The ratio is a property of the run, so it is read off the
    # run: `flat_lo`/`flat_hi` are the same paired differences without the clustering.
    ratios = [
        (block["hi"] - block["lo"]) / (block["flat_hi"] - block["flat_lo"])
        for block in payload.values()
        if isinstance(block, Mapping)
        and not isinstance(block.get("lo"), str)
        and "flat_lo" in block
        and block["flat_hi"] > block["flat_lo"]
    ]
    detail = (
        f"On this run it widens a comparison by {min(ratios):.2f}x to "
        f"{max(ratios):.2f}x, depending on how much of that "
        f"comparison's variance is between seasons rather than "
        f"between seeds. There is no single ratio."
        if ratios
        else "flat intervals are not in this artifact."
    )
    out.extend(wrap60("five markets, not three hundred draws. " + detail))

    out.append("")
    out.append("limits that hold regardless:")
    out.extend(
        wrap60(
            "no vintage preseason projections exist for any season, "
            "so this measures ORDERING and never the projections."
        )
    )
    out.extend(
        wrap60(
            "bots fitted to ADP are not people. They do not stack, "
            "reach for their own players, or panic."
        )
    )
    out.extend(
        wrap60(
            "the bootstrap multiplies OUTCOME samples, not MARKET "
            "samples. Five ADP vintages remain five."
        )
    )
    return out


def _b4_block(payload: Mapping[str, Any]) -> list[str]:
    """B4's own header: the projection, its accuracy, its boards, and the ceiling.

    PRINTED BEFORE THE COMPARISONS, deliberately. A reader who sees the arm numbers first will
    read them against zero; the only scale that makes them mean anything is what a board built
    from the season's realised lines was worth, and how good the projection feeding the honest
    arms actually is.
    """
    block = payload.get("projection") or {}
    out: list[str] = [""]
    out.append("THE PROJECTION, pre-registered before any arm ran:")
    out.extend(wrap60(str(block.get("pre_registration", "?"))))
    usable = block.get("usable_seasons") or []
    out.append(f"  usable target seasons: {', '.join(str(x) for x in usable)}")

    report = block.get("accuracy") or {}
    excluded = report.get("excluded_seasons") or []
    if excluded:
        out.append(f"  NOT usable: {', '.join(str(x) for x in excluded)}")
        out.extend(wrap60(str(report.get("excluded_because", "")), indent="    "))
    out.append("  accuracy against realised season points, and the")
    out.append("  same players ordered by ADP rank:")
    for season, got in sorted((report.get("seasons") or {}).items()):
        summary = got.get("summary") or {}
        out.append(
            f"    {season}  n={summary.get('n', 0):.0f}"
            f"  r={summary.get('corr', 0):+.2f}"
            f"  rho={summary.get('spearman', 0):+.2f}"
            f"  ADP rho={summary.get('adp_spearman', 0):+.2f}"
            f"  MAE={summary.get('mae', 0):.0f}"
        )
        for position, row in (got.get("by_position") or {}).items():
            out.append(
                f"      {position:<3s} n={row.get('n', 0):3d}"
                f"  r={row.get('corr', 0):+.2f}"
                f"  ADP rho={row.get('adp_spearman', 0):+.2f}"
                f"  MAE={row.get('mae', 0):5.1f}"
            )

    out.append("")
    out.append("THE BOARDS ARE NOT THE ADP LIST, which is G2 and is the")
    out.append("gate on this whole session. Of the drafted top 128:")
    for season, got in sorted((block.get("seasons") or {}).items()):
        rows = got.get("vs_adp") or {}
        for arm in ("audible_transform", "points_greedy", "hindsight_board"):
            row = rows.get(arm)
            if not row:
                continue
            out.append(
                f"  {season} {arm:<18s} {row['exact_of_128']:3d} exact"
                f"  {row['disagree_over_one_round']:3d} >1rd"
                f"  r={row['pearson']:+.3f}"
            )
    out.append("  replacement level, the whole of what separates")
    out.append("  audible_transform from points_greedy:")
    for season, got in sorted((block.get("seasons") or {}).items()):
        levels = got.get("replacement_level") or {}
        parts = " ".join(f"{k}:{v:.0f}" for k, v in sorted(levels.items()) if v)
        out.append(f"    {season}  {parts}")

    ceiling = payload.get("ceiling") or {}
    if ceiling:
        out.append("")
        out.append("READ EVERY ARM AGAINST THE CEILING, NOT AGAINST ZERO.")
        out.extend(
            wrap60(
                "A board built from the season's REALISED lines is what "
                "perfect foresight was worth over the market. The same "
                "null means opposite things at a ceiling of 40 and a "
                "ceiling of 400."
            )
        )
        for policy in ("prior", "oracle", "hindsight"):
            got = ceiling.get(policy)
            if not got:
                continue
            out.append(f"  {policy}: ceiling {got.get('ceiling', 0):+.1f} over adp")
            for name in ("transform_minus_adp", "points_minus_adp", "transform_minus_points"):
                if name in got:
                    out.append(f"    {name:<22s} {got[name]:+7.1f}% of it")
            if "share_undefined_because" in got:
                out.extend(wrap60(str(got["share_undefined_because"]), indent="    "))
    return out


def content_digest(payload: Mapping[str, Any]) -> str:
    """sha256 over everything the config determines. Wall clock is excluded, nothing else is.

    Digested over the CLEANED payload, which is what the file stores. Digesting the raw one
    meant the digest could not be recomputed from the artifact once `_clean` rounded a float,
    and it raised outright on an infinity -- which a single-season run legitimately produces,
    because one cluster has no interval.
    """
    stripped = {k: _clean(v) for k, v in payload.items() if k not in VOLATILE}
    return hashlib.sha256(canonical(stripped).encode("utf-8")).hexdigest()


def write(path: Path, payload: dict[str, Any]) -> Path:
    """Write the artifact: the mobile summary first, then the JSON body."""
    payload["schema_version"] = SCHEMA_VERSION
    payload["content_digest"] = content_digest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _clean(payload)
    body = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    header = "\n".join(f"# {line}" if line else "#" for line in summary_block(payload))
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    return path


def read(path: Path) -> dict[str, Any]:
    """Read an artifact back, ignoring the comment header."""
    text = path.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return json.loads(body)
