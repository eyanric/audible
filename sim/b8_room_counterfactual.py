"""How much of MFL 8-team's `transform - points` is the MARKET and how much is the ROOM?

    uv run --extra nflverse python -m sim.b8_room_counterfactual


The shipped mfl_8_std run puts RB and WR on the SCHEDULE clock, which takes them off the board
the bots pick from. This runs the identical config twice -- once as shipped, once with the
scheduled set forced back to B1's {DEF, K} and nothing else changed -- so the difference
between the two is the room misspecification and the remainder is the market.

NEITHER RUN IS A RESULT and the forced one is not a market that exists -- `room.fit_room`
DERIVES the scheduled set from the board, so overriding it describes a room no board produces.
It is here because the shipped `b8-mfl8` artifact fails G7, and a failed gate is worth more if
it comes with the size of what it invalidated.

Measured, five seasons, twenty seeds, everything else identical:

    transform - points   as shipped -83.7 [-132.0, -35.5]   B1 room +87.9 [-13.0, +188.8]
    transform - adp      as shipped -46.9 [-105.8, +12.0]   B1 room -49.0 [-168.3, +70.2]

So the room accounts for -171.6 of the first and +2.2 of the second. The apparent sign
reversal against FFC was the opponent model, not the market. The finding that survives every
market AND the room is that the transform does not beat ADP.
"""

import dataclasses
import tempfile
from pathlib import Path

from sim import artifact, room, runner

CONFIG = Path(__file__).resolve().parent / "configs" / "b8-mfl8.toml"
SEEDS = 20
KEYS = ("transform_minus_points", "transform_minus_adp", "real_minus_adp", "real_minus_shuffle")


def run(force_b1: bool) -> dict:
    base = runner.load_config(CONFIG)
    config = dataclasses.replace(
        base,
        name=f"b8-cf-{'b1room' if force_b1 else 'asis'}",
        seeds=tuple(range(SEEDS)),
        arms=("points_greedy", "audible_transform", "adp", "adp_board", "bot", "shuffle", "real"),
        wf_fit=(),
        wf_test=(),
    )
    real_fit = room.fit_room
    if force_b1:

        def forced(*args, **kwargs):
            fit = real_fit(*args, **kwargs)
            return dataclasses.replace(fit, scheduled=frozenset({"DEF", "K"}))

        room.fit_room = forced
    try:
        with tempfile.TemporaryDirectory(prefix="cf-") as state, tempfile.TemporaryDirectory(
            prefix="cf-ck-"
        ) as ck:
            return runner.execute(
                config, resume=False, state_dir=Path(state), checkpoint_dir=Path(ck),
                progress_every=100000,
            )
    finally:
        room.fit_room = real_fit


asis = run(False)
b1 = run(True)


def show(payload: dict, label: str) -> None:
    print(f"\n{label}   scheduled={payload['fit']['scheduled']}")
    for key in KEYS:
        d = payload.get(key)
        if d:
            print(f"   {key:26s} {d['mean']:+8.1f} [{d['lo']:+7.1f}, {d['hi']:+7.1f}]")
    print("   bots draft (mean of 16):")
    for arm in ("bot", "adp", "audible_transform", "points_greedy"):
        got = payload["arms"][arm].get("positions_drafted") or {}
        print(f"     {arm:18s} " + "  ".join(f"{k}:{v:.2f}" for k, v in sorted(got.items())))


show(asis, "AS SHIPPED (RB and WR on the schedule clock)")
show(b1, "FORCED to B1's scheduled set {DEF, K}")
print("\nthe room's share of each comparison:")
for key in KEYS:
    a, b = asis.get(key), b1.get(key)
    if a and b:
        print(f"   {key:26s} as-shipped {a['mean']:+8.1f}   B1-room {b['mean']:+8.1f}"
              f"   room accounts for {a['mean'] - b['mean']:+8.1f}")
print(f"\nseeds={SEEDS}  seasons={list(asis['seasons'])}  units={asis['units']} each")
runs = Path(__file__).resolve().parent / "runs"
artifact.write(runs / "b8-counterfactual-asis.json", asis)
artifact.write(runs / "b8-counterfactual-b1room.json", b1)
