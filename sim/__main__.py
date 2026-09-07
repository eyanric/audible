"""`python -m sim <command>`. The unattended entry point.

A module rather than a script, because `sim/__init__.py` is what rebinds the cache root away
from the live cockpit's, and `python sim/runner.py` would skip it -- which is exactly the
mistake `sim/backfill.py` already refuses at its own `__main__`.
"""

from __future__ import annotations

import sys

USAGE = """usage: python -m sim <command> [options]

commands:
  run     --config sim/configs/<name>.toml [--resume] [--out PATH] [--log PATH]
  room    the B1 room report (see `python -m sim.room --help`)

examples:
  uv run --extra nflverse python -m sim run --config sim/configs/b2-smoke.toml
  uv run --extra nflverse python -m sim run --config sim/configs/b2-default.toml --resume
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    command, rest = args[0], args[1:]
    if command == "run":
        from .runner import main as run_main

        return run_main(rest)
    if command == "room":
        from .room import main as room_main

        return room_main(rest)
    print(f"unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
