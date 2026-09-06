#!/usr/bin/env python
"""Render the two staleness states to PNG. Evidence for gates G1 and G2.

The 2026-09-05 failure was invisible *precisely because it was not on screen*, so "a test
asserts the boolean" is not the standard here -- somebody has to be able to look at the two
pictures and see that one of them is obviously wrong and the other is obviously fine.

Two shots, and the pair is the point:

  g2-pre-draft.png   draft not started, no pick ever, poll age arbitrary -> NO warning
  g1-silent.png      draft in progress, no pick for well over two clocks -> loud warning

G2 is the harder one and the reason this script renders both. An indicator that also lights
up on a quiet Tuesday afternoon is one nobody reads on draft night, so "it fires" is only
half a gate; "and it stays dark when it should" is the other half.

Nothing under src/ is modified: the cockpit is booted in a subprocess against a synthetic
board, and the two states are produced by setting the health clocks directly -- the same
idiom tests/test_ui_desktop.py already uses.

    uv run python scripts/shot-sync-staleness.py [--out docs/img]
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

BOOT = """
import sys, time
sys.path.insert(0, r"{src}")
from pathlib import Path
import uvicorn
from audible.config.loader import load_all_leagues
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import Pick
from audible.draft.service import CockpitService
from audible.server import create_app

TEAMS = 8
POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]

def entry(i):
    pos = POSITIONS[(i - 1) % len(POSITIONS)]
    return DraftEntry(
        player_id="p%03d" % i, name="Player %03d" % i, position=pos,
        eligible_positions=frozenset({{pos}}), team="XX", model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=(i % 17 == 0), scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i), adp_rank=i, value=0, flags=("riser",) if i % 5 == 0 else (),
    )

def slot_of(pick_no):
    rnd, idx = divmod(pick_no - 1, TEAMS)
    return idx + 1 if rnd % 2 == 0 else TEAMS - idx

cfg = load_all_leagues()["espn_green_hope"]
sd = Path(r"{state}"); sd.mkdir(parents=True, exist_ok=True)
[p.unlink() for p in sd.glob("*.json")]
svc = CockpitService(cfg, state_dir=sd, slot_override=1)
svc.board = DraftBoard("espn_green_hope", [entry(i) for i in range(1, 201)])
svc.session.draft_id = "shot"
svc.session.draft_status = "{status}"
svc.session.slot, svc.session.slot_source = 1, "override"
svc.session.picks = [
    Pick(pick_no=n, round=(n - 1) // TEAMS + 1, draft_slot=slot_of(n),
         player_id="p%03d" % n)
    for n in range(1, {picks} + 1)
]

now = time.time()
# The poll is HEALTHY in both shots. That is the entire trap being illustrated: every clock
# the cockpit had before this change reads green here.
svc.health.last_success = now
svc.health.poll_count = 412
svc.health.drafting_since = {drafting_since}
svc.health.last_pick_change = {last_pick_change}

uvicorn.run(create_app(svc, warm=False), host="127.0.0.1", port={port},
            log_level="warning")
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait(port: int, timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise SystemExit(f"cockpit on {port} never came up")


def shoot(
    name: str, status: str, picks: int, silence_s: float | None, out: Path
) -> tuple[dict[str, Any], Path]:
    from playwright.sync_api import sync_playwright

    port = _free_port()
    state = out / f".state-{name}"
    drafting_since = "None" if silence_s is None else f"now - {silence_s}"
    boot = BOOT.format(
        src=SRC, state=state, status=status, picks=picks, port=port,
        drafting_since=drafting_since, last_pick_change="None",
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", boot], cwd=REPO,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        _wait(port)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 950})
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            # Two poll cycles, so the chip has rendered from served state rather than from
            # its "waiting for first update" placeholder.
            page.wait_for_timeout(2500)
            chip = page.locator("#syncChip")
            observed = {
                "chip_class": chip.get_attribute("class") or "",
                "chip_text": (chip.inner_text() or "").strip(),
                "alert_hidden": page.locator("#alert").is_hidden(),
                "alert_text": (page.locator("#alert").inner_text() or "").strip()
                if page.locator("#alert").is_visible() else "",
            }
            path = out / f"{name}.png"
            page.screenshot(path=str(path))
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        shutil.rmtree(state, ignore_errors=True)

    print(f"{name}:")
    print(f"  chip class : {observed['chip_class']!r}")
    print(f"  chip text  : {observed['chip_text']!r}")
    print(f"  alert      : {'hidden' if observed['alert_hidden'] else observed['alert_text']}")
    print(f"  -> {path}")
    return observed, path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "img")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # G2 first: the state that must produce NOTHING.
    g2, _ = shoot("g2-pre-draft", status="pre_draft", picks=0, silence_s=None, out=args.out)
    # G1: in progress, and not one pick has ever arrived.
    g1, _ = shoot("g1-silent", status="drafting", picks=0, silence_s=412.0, out=args.out)

    # ASSERT, so this can go red. A screenshot script that only ever exits 0 documents the
    # states rather than gating them, and would have written a green-looking g1-silent.png
    # just as happily if the indicator had never fired.
    problems: list[str] = []
    if "dead" not in g1["chip_class"].split():
        problems.append(f"G1: chip should be `dead`, got {g1['chip_class']!r}")
    if "NO PICKS" not in g1["chip_text"].upper():
        problems.append(f"G1: chip text should name it, got {g1['chip_text']!r}")
    if g1["alert_hidden"] or "NO PICKS ARRIVING" not in g1["alert_text"].upper():
        problems.append("G1: the alert strip should be up and say so")
    if "dead" in g2["chip_class"].split():
        problems.append(f"G2: chip must NOT be `dead` pre-draft, got {g2['chip_class']!r}")
    if "NO PICKS" in g2["chip_text"].upper():
        problems.append(f"G2: false alarm in the chip: {g2['chip_text']!r}")
    if "NO PICKS ARRIVING" in g2["alert_text"].upper():
        problems.append("G2: false alarm in the alert strip")

    print("")
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        return 1
    print("both states render as specified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
