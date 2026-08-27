"""End-to-end QA for the draft cockpit: real browser, real events, and it LISTENS.

    uv run --extra nflverse python scripts/qa-cockpit.py
    uv run --extra nflverse python scripts/qa-cockpit.py --league sleeper_boyfun
    uv run --extra nflverse python scripts/qa-cockpit.py --url http://127.0.0.1:8080  (read-only)

WHY THIS EXISTS. The unit tests assert strings against the served HTML, which cannot fail
when the JavaScript is broken -- a single uncaught exception kills the whole IIFE and every
control at once while every assertion still passes. Earlier ad-hoc CDP harnesses could not
catch it either, because their websocket read loop DISCARDED any frame that was not a reply
to the request just sent, which is exactly where `Runtime.exceptionThrown` arrives. This
collects events first and fails the run on any of them.

SAFETY. By default this starts its OWN cockpit on an unused port with an isolated
state_dir, drives it, and tears it down -- it marks players, so it must never be pointed at
the real draft session. `--url` attaches to an already-running server and then runs only the
read-only checks, for looking at a live instance.

Exit code is 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

# The cockpit renders real glyphs (the Enter arrow U+21B5, en dashes) and this harness
# echoes them back in check detail. A Windows console is cp1252, where printing one raises
# AFTER the assertion was recorded but BEFORE the summary -- an incomplete run that exits 1
# and reads exactly like an ordinary failure. Never let the reporter break the report.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

SNAP = """
(function(){
  function txt(el){return el?(el.textContent||"").trim():null;}
  function shown(el){ if(!el) return false;
    var r=el.getBoundingClientRect();
    return !el.hasAttribute("hidden") && r.width>0 && r.height>0; }
  var selAny=document.querySelector("tr.sel");
  var firstBest=document.querySelector("#bestBody tr");
  var hintEl=document.getElementById("enterHint");
  return JSON.stringify({
    focus:(document.activeElement&&(document.activeElement.id||document.activeElement.tagName))||null,
    rows:document.querySelectorAll("#bestBody tr").length,
    grabRows:document.querySelectorAll("#grabBody tr").length,
    selCount:document.querySelectorAll("tr.sel").length,
    selName:selAny?txt(selAny.querySelector(".pname")):null,
    firstName:firstBest?txt(firstBest.querySelector(".pname")):null,
    pick:txt(document.getElementById("pickNo")),
    q:(document.getElementById("q")||{}).value,
    hint:shown(hintEl)?txt(hintEl):null,
    legend:txt(document.getElementById("legendDigits")),
    tabs:[].slice.call(document.querySelectorAll("#tabs button"))
          .filter(function(b){return !b.hidden;}).map(function(b){return b.dataset.key;}),
    hOverflow:document.documentElement.scrollWidth>innerWidth+1
  });
})()
"""


USAGE_PROBE = """
(function(){
  var rows=[].slice.call(document.querySelectorAll("#bestBody tr")).slice(0,40);
  function nums(sel){
    return rows.filter(function(r){
      var c=r.querySelectorAll(sel);
      return c.length && /^[0-9]+$/.test((c[0].textContent||"").trim());
    }).length;
  }
  return JSON.stringify({
    rows:rows.length,
    tgtNums:nums(".c-use"),
    rteNums:rows.filter(function(r){
      var c=r.querySelectorAll(".c-use");
      return c.length>1 && /^[0-9]+$/.test((c[1].textContent||"").trim());
    }).length,
    byes:rows.filter(function(r){
      var b=r.querySelector(".c-team .bye");
      return !!b && /^[0-9]+$/.test((b.textContent||"").trim());
    }).length
  });
})()
"""

VIEWPORT_SIZES = [(1920, 1080), (2560, 1440)]

LAYOUT = """
(function(){
  function m(sel){
    var e=document.querySelector(sel); if(!e) return null;
    var r=e.getBoundingClientRect();
    return {w:Math.round(r.width), h:Math.round(r.height),
            l:Math.round(r.left), r:Math.round(r.right),
            rows:e.querySelectorAll("tr").length,
            vis:!(r.width===0||r.height===0||getComputedStyle(e).display==="none")};
  }
  return JSON.stringify({
    vw:innerWidth, vh:innerHeight,
    scrollWidth:document.documentElement.scrollWidth,
    hOverflow:document.documentElement.scrollWidth>innerWidth+1,
    cols:{left:m(".col-left"), mid:m(".col-mid"), right:m(".col-right")}
  });
})()
"""


def pick_int(text: str | None) -> int | None:
    """The integer out of 'PICK 12' -- and out of 'PICK 8+9' at the snake turn.

    #pickNo is the only mark/undo oracle this suite has, and its FORMAT changes at the
    turn, so comparing the raw strings would read a format flip as a successful mark.
    """
    m = re.match(r"PICK (\d+)", (text or "").strip())
    return int(m.group(1)) if m else None


async def board_names(bus: Bus) -> list[str]:
    v = await bus.ev(
        "JSON.stringify([].slice.call(document.querySelectorAll('#bestBody .pname'))"
        ".map(function(e){return (e.textContent||'').trim();}))")
    return json.loads(v or "[]")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_browser() -> str:
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("no Edge/Chrome found; QA needs a Chromium browser for CDP")


class Bus:
    """A CDP connection that KEEPS events instead of dropping them."""

    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.errors: list[str] = []
        self.console: list[str] = []

    def _record(self, m: dict) -> None:
        meth, p = m.get("method"), m.get("params", {})
        if meth == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            desc = (d.get("exception") or {}).get("description") or d.get("text")
            self.errors.append("{} @{}:{}".format(str(desc).split("\n")[0],
                                              d.get("url", "?"), d.get("lineNumber")))
        elif meth == "Log.entryAdded":
            e = p.get("entry", {})
            if e.get("level") == "error":
                self.errors.append("[log] {} @{}:{}".format(e.get("text"), e.get("url", "?"),
                                                        e.get("lineNumber")))
        elif meth == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
            self.console.append(" ".join(str(a.get("value", a.get("description", "")))
                                         for a in p.get("args", [])))

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + CDP_TIMEOUT_S
        while True:
            if time.time() > deadline:
                # This used to be a bare `await recv()`. A wedged page hung it forever: no
                # summary, no exit code, and the finally that kills the browser and the
                # cockpit never ran, so both leaked. A hang is now a red run like any other.
                raise CdpTimeout(f"CDP timed out after {CDP_TIMEOUT_S}s on {method}")
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
            except TimeoutError:
                continue
            m = json.loads(raw)
            if m.get("id") == mid:
                return m
            self._record(m)

    async def drain(self, seconds: float = 0.5) -> None:
        end = time.time() + seconds
        while time.time() < end:
            with contextlib.suppress(asyncio.TimeoutError):
                self._record(json.loads(await asyncio.wait_for(self.ws.recv(), timeout=0.12)))

    async def ev(self, expr: str):
        r = await self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        if r.get("result", {}).get("exceptionDetails"):
            self.errors.append("[eval] {}".format(r["result"]["exceptionDetails"].get("text")))
        return r["result"]["result"].get("value")

    async def snap(self) -> dict:
        return json.loads(await self.ev(SNAP))

    async def key(self, k, text=None, mods=0, code=None) -> None:
        p = {"type": "keyDown", "key": k, "modifiers": mods}
        if text is not None:
            p["text"] = text
        if code:
            p["code"] = code
        await self.send("Input.dispatchKeyEvent", p)
        await self.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": k, "modifiers": mods})
        await self.drain(0.2)

    async def typ(self, s: str) -> None:
        for ch in s:
            await self.key(ch, text=ch)

    async def click(self, x, y) -> None:
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent",
                            {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})
            await asyncio.sleep(0.05)
        await self.drain(0.45)

    async def box(self, sel: str, nth: int = 0):
        sel_js = json.dumps(sel)
        v = await self.ev(
            f"(function(){{var e=document.querySelectorAll({sel_js})[{nth}];"
            f"if(!e)return 'null';var r=e.getBoundingClientRect();"
            f"return JSON.stringify({{x:r.x+r.width/2,y:r.y+r.height/2}});}})()")
        return json.loads(v) if v and v != "null" else None


# Checks a run must produce to be COMPLETE. Without this, "the suite went red" is
# ambiguous: an assertion that caught a regression and a harness that crashed on check 11
# both exit 1. A mutation the suite CRASHES on is not a mutation the suite DETECTS, and a
# mutation gate that cannot tell those apart certifies nothing. Any name here that never
# ran is reported as its own failure.
READONLY_CHECKS: tuple[str, ...] = (
    "no uncaught JS exceptions",
    "no console errors",
    "board rendered rows",
    "search box focused on load",
    "no horizontal overflow at 1920",
    "digit legend matches visible tabs",
    "usage columns render real numbers",
    "bye weeks render on the team cell",
    "clicking a row selects exactly one",
    "arrow moves the highlight",
    "caret stays in the search box",
    "no JS exceptions during the whole run",
    "no console errors during the whole run",
)

WRITE_CHECKS: tuple[str, ...] = (
    "typing filters the board",
    "typing highlights a row and shows the hint",
    "Enter marked the highlighted row",
    "Enter advanced the pick by exactly one",
    "Enter marked the player that was highlighted",
    "query cleared and box still focused",
    "t marked the selection",
    "t advanced the pick by exactly one",
    "ctrl+z undid it",
    "ctrl+z moved the pick back by exactly one",
    "u undid another",
    "u moved the pick back by exactly one",
    "clicking X marked a player",
    "clicking X advanced the pick by exactly one",
    "a space in the box raises no Enter hint",
    "a space in the box never marks anybody",
    "Enter on a focused button does not mark",
    "key 'g' jumps to the grab list",
    "key 'b' jumps to the best list",
)

# Phase 2: what guards picks rather than pixels. These need no browser -- they run
# in-process against the pinned board with an isolated state dir.
BOARD_CHECKS: tuple[str, ...] = (
    "board vorp ranks are a clean 1..N sequence",
    "DEF vorp stays under the startable skill floor",
    "K vorp stays under the startable skill floor",
    "best_available returns a populated board",
    "player_lookup agrees with best_available",
    "compare agrees with best_available",
    "recommend agrees with the same board",
    "slot-8 dry run fills every starting slot",
    "slot-8 roster has no short slot",
    "no D/ST before round 13",
    # Lane 1: displayed usage context. None of it enters the sort, and the check named
    # "usage did not enter the sort" is what keeps that true rather than merely intended.
    "pinned usage table is not degraded",
    "usage did not enter the sort",
    "target share covers the draftable window",
    "route participation covers the draftable window",
    "every board team resolves to a bye week",
    "bye weeks are inside the regular season",
    "usage shares are fractions in 0..1",
    "_slim carries every usage field",
    "_slim usage fields are populated, not just present",
    "ADP is priced deep enough to rank the draftable window",
    "ADP value tracks market rank (a pick number, not a round code)",
    "the realistic draft takes exactly 128",
    "a startable K is still on the wire after 128 picks",
    "a startable D/ST is still on the wire after 128 picks",
    "no startable RB is left on the wire after 128 picks",
    "one replacement baseline per position",
)

VIEWPORT_CHECKS: tuple[str, ...] = (
    "no horizontal overflow at 1920x1080",
    "left column is not stranded at 1920x1080",
    "mid column is not stranded at 1920x1080",
    "right column is not stranded at 1920x1080",
    "no horizontal overflow at 2560x1440",
    "left column is not stranded at 2560x1440",
    "mid column is not stranded at 2560x1440",
    "right column is not stranded at 2560x1440",
)

# Seat 8 of 8 picks back-to-back at the snake turns: 8+9, 24+25, 40+41, 56+57. Those are
# the moments the cockpit has to say TWO picks are on the clock, because showing a single
# pick number there reads as one pick and the second gets made in a hurry.
CLOCK_CHECKS: tuple[str, ...] = (
    "clock state is right at pick 8",
    "cockpit renders the pick-8 clock",
    "clock state is right at pick 9",
    "cockpit renders the pick-9 clock",
    "clock state is right at pick 24",
    "cockpit renders the pick-24 clock",
    "clock state is right at pick 25",
    "cockpit renders the pick-25 clock",
    "clock state is right at pick 40",
    "cockpit renders the pick-40 clock",
    "clock state is right at pick 41",
    "cockpit renders the pick-41 clock",
    "clock state is right at pick 56",
    "cockpit renders the pick-56 clock",
    "clock state is right at pick 57",
    "cockpit renders the pick-57 clock",
)

# No single CDP command should ever take this long. Past it the page is wedged, and a
# wedged page has to produce a red verdict rather than a process that never returns.
CDP_TIMEOUT_S = 30.0


class CdpTimeout(RuntimeError):
    """Its own type so the overall deadline can never be mistaken for the 1s poll."""

RESULTS: list[tuple[str, bool, str]] = []
ABORT: list[str] = []  # non-empty => run_suite raised; the run is INCOMPLETE, not just red


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    verdict = "PASS" if ok else "**FAIL**"
    print(f"  {name:<46} {verdict}  {detail}")


async def run_suite(bus: Bus, url: str, readonly: bool) -> None:
    await bus.send("Page.enable")
    await bus.send("Runtime.enable")
    await bus.send("Log.enable")
    await bus.send("Network.enable")
    await bus.send("Network.setCacheDisabled", {"cacheDisabled": True})
    await bus.send("Emulation.setDeviceMetricsOverride",
                   {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False})
    await bus.send("Page.navigate", {"url": url})

    s = {}
    for _ in range(24):
        await bus.drain(0.5)
        s = await bus.snap()
        if s.get("rows"):
            break

    print("=" * 74)
    print("1. PAGE HEALTH")
    print("=" * 74)
    check("no uncaught JS exceptions", not bus.errors, "; ".join(bus.errors[:3]))
    check("no console errors", not bus.console, "; ".join(bus.console[:2]))
    check("board rendered rows", s.get("rows", 0) > 0,
          "best={} grab={}".format(s.get("rows"), s.get("grabRows")))
    check("search box focused on load", s.get("focus") == "q", "focus={}".format(s.get("focus")))
    check("no horizontal overflow at 1920", not s.get("hOverflow"))
    check("digit legend matches visible tabs",
          s.get("legend") == f"0-{len(s.get('tabs', [])) - 1}",
          "legend={} tabs={}".format(s.get("legend"), s.get("tabs")))

    # Everything below drives a cockpit that has to be ALIVE: it clicks rows by
    # coordinate, reads the pick number, waits on a poll. When the IIFE is dead none of
    # that exists, and the first click raises -- which is red, but red for the wrong
    # reason and with two thirds of the suite silently unrun. The checks above have
    # already recorded the real failure; stopping cleanly here lets the manifest report
    # every remaining check as its own explicit failure, so the run is COMPLETE and red
    # rather than truncated and red. A dead page is the loudest result this suite has.
    # Gated on the BOARD, not on bus.errors: a JS error with a rendered board still leaves
    # every control drivable, and the run is more useful for having tested them. Only a board
    # that never rendered makes the rest of the suite meaningless.
    if not s.get("rows"):
        print()
        print("  the cockpit is not alive -- no rows rendered. Every interaction check below")
        print("  is unrunnable, and each is reported as its own failure.")
        return

    print()
    print("=" * 74)
    print("2. MOUSE: CLICK A ROW SELECTS IT")
    print("=" * 74)
    row = await bus.box("#bestBody tr", 2)
    await bus.click(row["x"], row["y"])
    a = await bus.snap()
    check("clicking a row selects exactly one", a["selCount"] == 1 and bool(a["selName"]),
          "sel={!r}".format(a["selName"]))

    print()
    print("=" * 74)
    print("3. ARROWS MOVE THE HIGHLIGHT FROM THE SEARCH BOX")
    print("=" * 74)
    qb = await bus.box("#q")
    await bus.click(qb["x"], qb["y"])
    await bus.key("ArrowDown", code="ArrowDown")
    b1 = await bus.snap()
    await bus.key("ArrowDown", code="ArrowDown")
    b2 = await bus.snap()
    check("arrow moves the highlight", b1["selName"] != b2["selName"],
          "{!r} -> {!r}".format(b1["selName"], b2["selName"]))
    check("caret stays in the search box", b2["focus"] == "q", "focus={}".format(b2["focus"]))

    print()
    print("=" * 74)
    print("3a. USAGE CONTEXT IS ON THE BOARD")
    print("=" * 74)
    use = json.loads(await bus.ev(USAGE_PROBE))
    # A column of dots is what a broken join looks like from the outside: the markup is
    # perfect and every number is missing. So this counts REAL values, not cells.
    check("usage columns render real numbers",
          use["tgtNums"] >= 20 and use["rteNums"] >= 20,
          "of {} rows: {} target-share, {} route-% ".format(
              use["rows"], use["tgtNums"], use["rteNums"]))
    check("bye weeks render on the team cell", use["byes"] >= 20,
          "{} of {} rows carry a bye".format(use["byes"], use["rows"]))

    print()
    print("=" * 74)
    print("3b. LAYOUT AT EVERY REAL SCREEN")
    print("=" * 74)
    await viewport_section(bus)

    if readonly:
        print("\n  (read-only mode: skipping every check that would mark a player)")
        return

    print()
    print("=" * 74)
    print("4. KEYBOARD: TYPE-AHEAD + ENTER MARKS THE HIGHLIGHTED ROW")
    print("=" * 74)
    await bus.key("Escape", code="Escape")
    await bus.drain(0.3)
    qb = await bus.box("#q")
    await bus.click(qb["x"], qb["y"])
    # Type a fragment of a player who is definitely still ON the board right now, rather
    # than a hardcoded name an earlier step may already have marked.
    fresh = (await bus.snap())["firstName"] or ""
    frag = fresh.split()[-1][:6].lower()
    await bus.typ(frag)
    await bus.drain(0.6)
    mid = await bus.snap()
    check("typing filters the board", 0 < mid["rows"] < 140,
          "{!r} -> rows={}".format(frag, mid["rows"]))
    check("typing highlights a row and shows the hint",
          bool(mid["selName"]) and bool(mid["hint"]),
          "sel={!r} hint={!r}".format(mid["selName"], mid["hint"]))
    before = mid["pick"]
    names_before = await board_names(bus)
    await bus.key("Enter", code="Enter")
    await bus.drain(1.0)
    c = await bus.snap()
    check("Enter marked the highlighted row", c["pick"] != before,
          "pick {!r} -> {!r}".format(before, c["pick"]))
    check("Enter advanced the pick by exactly one",
          pick_int(c["pick"]) == (pick_int(before) or 0) + 1,
          "pick {!r} -> {!r}".format(before, c["pick"]))
    # Identity, not just motion: the row Enter took must be the row that was highlighted.
    # The setup is asserted too, so this cannot pass by the name never having been there.
    names_after = await board_names(bus)
    was_there = mid["selName"] in names_before
    check("Enter marked the player that was highlighted",
          was_there and mid["selName"] not in names_after,
          "{!r} on board before={} after={}".format(
              mid["selName"], was_there, mid["selName"] in names_after))
    check("query cleared and box still focused", c["q"] == "" and c["focus"] == "q",
          "q={!r} focus={}".format(c["q"], c["focus"]))

    print()
    print("=" * 74)
    print("5. KEYBOARD: t MARKS, ctrl+z AND u UNDO")
    print("=" * 74)
    await bus.key("Escape", code="Escape")
    await bus.drain(0.3)
    row = await bus.box("#bestBody tr", 1)
    await bus.click(row["x"], row["y"])
    before = (await bus.snap())["pick"]
    await bus.key("t", text="t")
    await bus.drain(1.0)
    c = await bus.snap()
    check("t marked the selection", c["pick"] != before,
          f"pick {before!r} -> {c['pick']!r}")
    check("t advanced the pick by exactly one",
          pick_int(c["pick"]) == (pick_int(before) or 0) + 1,
          f"pick {before!r} -> {c['pick']!r}")
    before = c["pick"]
    await bus.key("z", code="KeyZ", mods=2)
    await bus.drain(1.0)
    c = await bus.snap()
    check("ctrl+z undid it", c["pick"] != before, "pick {!r} -> {!r}".format(before, c["pick"]))
    check("ctrl+z moved the pick back by exactly one",
          pick_int(c["pick"]) == (pick_int(before) or 0) - 1,
          "pick {!r} -> {!r}".format(before, c["pick"]))
    before = c["pick"]
    await bus.key("u", text="u")
    await bus.drain(1.0)
    c = await bus.snap()
    check("u undid another", c["pick"] != before, "pick {!r} -> {!r}".format(before, c["pick"]))
    check("u moved the pick back by exactly one",
          pick_int(c["pick"]) == (pick_int(before) or 0) - 1,
          "pick {!r} -> {!r}".format(before, c["pick"]))

    print()
    print("=" * 74)
    print("6. MOUSE: THE X BUTTON MARKS")
    print("=" * 74)
    before = (await bus.snap())["pick"]
    mk = await bus.box("#bestBody tr .mark", 0)
    await bus.click(mk["x"], mk["y"])
    await bus.drain(1.0)
    c = await bus.snap()
    check("clicking X marked a player", c["pick"] != before,
          "pick {!r} -> {!r}".format(before, c["pick"]))
    check("clicking X advanced the pick by exactly one",
          pick_int(c["pick"]) == (pick_int(before) or 0) + 1,
          "pick {!r} -> {!r}".format(before, c["pick"]))

    print()
    print("=" * 74)
    print("6b. THE TWO WAYS ENTER MARKS SOMEBODY YOU DID NOT CHOOSE")
    print("=" * 74)

    # A space is a plausible mis-press: it is the advertised pause key, and pause is dead
    # while the box has focus, which it does from load. If a space counts as a query, Enter
    # marks the top of an UNFILTERED board -- the #1 player overall, gone in two keystrokes.
    await bus.key("Escape", code="Escape")
    await bus.drain(0.3)
    qb = await bus.box("#q")
    await bus.click(qb["x"], qb["y"])
    before = (await bus.snap())["pick"]
    await bus.key(" ", text=" ")
    await bus.drain(0.5)
    spaced = await bus.snap()
    check("a space in the box raises no Enter hint", spaced["hint"] is None,
          "hint={!r}".format(spaced["hint"]))
    await bus.key("Enter", code="Enter")
    await bus.drain(1.0)
    c = await bus.snap()
    check("a space in the box never marks anybody", c["pick"] == before,
          "pick {!r} -> {!r}".format(before, c["pick"]))
    await bus.key("Escape", code="Escape")
    await bus.drain(0.3)

    # Enter is the destructive key and it is the one WITHOUT the focused-BUTTON guard that
    # Space has. Focus stays on a button after any click, so Enter right after touching
    # pause, undo or a tab fires a mark against whatever row is still selected.
    row = await bus.box("#bestBody tr", 1)
    await bus.click(row["x"], row["y"])
    pb = await bus.box("#pauseBtn")
    await bus.click(pb["x"], pb["y"])
    staged = await bus.snap()
    focus_tag = await bus.ev("(document.activeElement||{}).tagName")
    before = staged["pick"]
    await bus.key("Enter", code="Enter")
    await bus.drain(1.0)
    c = await bus.snap()
    # The setup is asserted too. If the click stopped focusing the button or cleared the
    # selection, this scenario stops exercising the bug -- and a check that silently stops
    # testing anything is worse than no check, so that fails here rather than passing.
    check("Enter on a focused button does not mark",
          c["pick"] == before and staged["selCount"] == 1 and focus_tag == "BUTTON",
          "sel={} focus={} pick {!r} -> {!r}".format(
              staged["selCount"], focus_tag, before, c["pick"]))
    await bus.click(pb["x"], pb["y"])  # unpause: the clock section needs polling alive
    await bus.drain(0.5)

    print()
    print("=" * 74)
    print("7. SECTION KEYS")
    print("=" * 74)
    for k, want in (("g", "grab"), ("b", "best")):
        await bus.key(k, text=k)
        await bus.drain(0.4)
        got = await bus.ev("(function(){var r=document.querySelector('tr.sel');"
                           "return r?(r.closest('#grabBody')?'grab':'best'):null;})()")
        check(f"key {k!r} jumps to the {want} list", got == want, f"scope={got}")

    print()
    print("=" * 74)
    print("8. TWO PICKS ON THE CLOCK AT EVERY SNAKE TURN")
    print("=" * 74)
    await clock_section(bus, url)


async def viewport_section(bus: Bus) -> None:
    """Both screens this actually gets read on, and nothing stranded on either.

    The board is a three-column grid whose middle column caps at 1240px, so the outer two
    absorb everything above that. A column that collapses to nothing, or gets pushed past
    the right edge, still renders its rows -- every string assertion keeps passing while
    half the cockpit is off-screen. So this measures geometry, not markup."""
    for w, h in VIEWPORT_SIZES:
        await bus.send("Emulation.setDeviceMetricsOverride",
                       {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        await bus.drain(0.7)
        lay = json.loads(await bus.ev(LAYOUT))
        tag = f"{w}x{h}"
        check(f"no horizontal overflow at {tag}", not lay["hOverflow"],
              "scrollWidth={} vw={}".format(lay["scrollWidth"], lay["vw"]))
        for name in ("left", "mid", "right"):
            c = lay["cols"].get(name)
            ok = bool(c) and c["vis"] and c["w"] >= 150 and c["l"] >= -1 and c["r"] <= w + 1
            check(f"{name} column is not stranded at {tag}", ok,
                  "missing" if not c else
                  "w={} x=[{},{}] rows={}".format(c["w"], c["l"], c["r"], c["rows"]))
    # every later section clicks by coordinate, so hand the page back at the size they expect
    await bus.send("Emulation.setDeviceMetricsOverride",
                   {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False})
    await bus.drain(0.5)


def _api(url: str, path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(url.rstrip("/") + path)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=10) as r:
        return json.loads(r.read())


async def clock_section(bus: Bus, url: str) -> None:
    """The snake turn: seat 8 of 8 is on the clock twice in a row at 8+9, 24+25, 40+41, 56+57.

    Driven over the API rather than by 56 clicks, because the thing under test is what the
    cockpit SAYS at that pick, not how the picks got there. The state is asserted against the
    same `clock` dict the page reads, and then the rendered pick number is read back out of
    the DOM -- both halves, because either can be right while the other is wrong."""
    for target in (8, 9, 24, 25, 40, 41, 56, 57):
        state = _api(url, "/api/state")
        guard = 0
        while (state["clock"] or {}).get("current_pick", 0) < target and guard < 200:
            pool = state.get("best_available") or []
            if not pool:
                break
            state = _api(url, "/api/taken", {"player_id": pool[0]["id"]})
            guard += 1

        clock = state.get("clock") or {}
        cur = clock.get("current_pick")
        # 8, 24, 40, 56 are the turn (two mine); 9, 25, 41, 57 are the far side of it (one).
        two_expected = target % 16 == 8
        two_actual = (
            clock.get("picks_until_me") == 0
            and clock.get("opponent_picks_until_horizon") == 0
            and clock.get("survival_horizon") is not None
        )
        check(f"clock state is right at pick {target}",
              cur == target and two_actual == two_expected,
              "pick={} two={} (want {}) until_me={} rivals={} horizon={}".format(
                  cur, two_actual, two_expected, clock.get("picks_until_me"),
                  clock.get("opponent_picks_until_horizon"), clock.get("survival_horizon")))

        await bus.drain(2.6)  # let the page poll (POLL_MS = 2000) and repaint
        shown = await bus.ev("(document.getElementById('pickNo')||{}).textContent")
        shown = (shown or "").strip()
        want = (f"PICK {target}+{clock.get('survival_horizon')}" if two_expected
                else f"PICK {target}")
        check(f"cockpit renders the pick-{target} clock", shown == want,
              f"shows {shown!r} want {want!r}")


async def drive(url: str, readonly: bool) -> None:
    import websockets

    cdp = free_port()
    profile = Path(tempfile.gettempdir()) / f"audible-qa-{cdp}"
    proc = subprocess.Popen(
        [find_browser(), "--headless=new", "--disable-gpu", "--no-first-run",
         "--disable-extensions", f"--remote-debugging-port={cdp}",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        tgt = None
        for _ in range(60):
            try:
                listing = f"http://127.0.0.1:{cdp}/json/list"
                with urllib.request.urlopen(listing, timeout=1) as r:
                    tgt = next(t for t in json.load(r) if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        if not tgt:
            raise SystemExit("browser did not expose a CDP page target")
        async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=40_000_000) as ws:
            bus = Bus(ws)
            try:
                await run_suite(bus, url, readonly)
            except Exception:
                ABORT.append(traceback.format_exc())
            # The load-time pair catches a cockpit that is dead on arrival. This pair catches
            # the one that dies UNDER USE -- on a click, a keystroke, a mark, an undo. Those
            # exceptions were collected and printed and asserted on by NOTHING, so the suite
            # would print the very exception it exists to catch and still exit 0.
            await bus.drain(1.5)
            check("no JS exceptions during the whole run", not bus.errors,
                  "; ".join(bus.errors[:3]))
            check("no console errors during the whole run", not bus.console,
                  "; ".join(bus.console[:2]))
            print()
            print("=" * 74)
            print("JS ERRORS / CONSOLE")
            print("=" * 74)
            for e in bus.errors:
                print(f"  EXC {e}")
            for c in bus.console:
                print(f"  CON {c}")
            if not bus.errors and not bus.console:
                print("  (none)")
    finally:
        proc.terminate()


def start_server(league: str, port: int, state_dir: Path,
                 live_board: bool = False) -> subprocess.Popen:
    """A throwaway cockpit: PINNED board, ISOLATED state, so QA never touches a real draft.

    The board is loaded from scripts/fixtures/qa-board-<league>.json rather than built.
    A live board makes the oracle non-deterministic in the worst way: a UI regression and an
    overnight ADP move produce the same red, and yesterday's red does not reproduce today.
    `--live-board` opts back in, for a deliberate against-reality check outside the loop.
    """
    src = REPO / "src"
    scripts = REPO / "scripts"
    board_expr = "build_board(cfg)" if live_board else f"load_board({league!r})"
    # Usage is pinned in the same fixture as the board. A live board gets live usage, so
    # --live-board stays one honest check against reality rather than a hybrid.
    usage_expr = ("load_usage()" if live_board else f"load_usage_table({league!r})")
    usage_import = ("from audible.draft.usage import load_usage" if live_board
                    else "from qa_board_fixture import load_usage_table")
    board_import = ("from audible.draft.board import build_board" if live_board
                    else "from qa_board_fixture import load_board")
    boot = "\n".join([
        f"import sys,time;sys.path.insert(0,r'{src}');sys.path.insert(0,r'{scripts}')",
        "from pathlib import Path",
        "import uvicorn",
        "from audible.config.loader import load_all_leagues",
        board_import,
        usage_import,
        "from audible.draft.service import CockpitService",
        "from audible.server import create_app",
        f"cfg=load_all_leagues()[{league!r}]",
        f"sd=Path({str(state_dir)!r}); sd.mkdir(parents=True,exist_ok=True)",
        "[p.unlink() for p in sd.glob('*.json')]",
        "svc=CockpitService(cfg,state_dir=sd,slot_override=8)",
        f"svc.board={board_expr}",
        f"svc.usage={usage_expr}",
        "svc.session.draft_id='qa'; svc.session.draft_status='drafting'",
        "svc.session.slot, svc.session.slot_source = 8,'override'",
        "svc.health.last_success=time.time()",
        f"uvicorn.run(create_app(svc,warm=False),host='127.0.0.1',port={port},"
        "log_level='warning')",
    ])
    return subprocess.Popen([sys.executable, "-c", boot], cwd=REPO,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--url", default=None,
                    help="attach to a running cockpit; runs READ-ONLY checks only")
    ap.add_argument("--live-board", action="store_true",
                    help="build the board from live data instead of the pinned fixture")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write a machine-readable verdict here (used by the mutation gate)")
    args = ap.parse_args()

    if args.url:
        print(f"attached to {args.url} -- READ-ONLY checks only\n")
        asyncio.run(drive(args.url.rstrip("/") + "/", readonly=True))
    else:
        port = free_port()
        with tempfile.TemporaryDirectory(prefix="audible-qa-state-") as sd:
            board_src = "LIVE board" if args.live_board else "pinned board"
            print(f"starting an isolated cockpit ({board_src}): league={args.league} "
                  f"port={port} state={sd}\n")
            proc = start_server(args.league, port, Path(sd), live_board=args.live_board)
            try:
                for _ in range(90):
                    try:
                        health = f"http://127.0.0.1:{port}/healthz"
                        with urllib.request.urlopen(health, timeout=2) as r:
                            if r.status == 200:
                                break
                    except Exception:
                        pass
                    time.sleep(1)
                asyncio.run(drive(f"http://127.0.0.1:{port}/", readonly=False))
            finally:
                proc.terminate()

    print()
    print("=" * 74)
    print("9. BOARD INVARIANTS -- picks, not pixels")
    print("=" * 74)
    try:
        import qa_board_invariants
        with tempfile.TemporaryDirectory(prefix="audible-qa-inv-") as inv:
            qa_board_invariants.run(check, args.league, Path(inv))
            qa_board_invariants.run_usage(check, args.league, Path(inv))
            qa_board_invariants.run_adp_calibration(check, args.league)
            qa_board_invariants.run_waiver_invariants(check, args.league)
    except Exception:
        ABORT.append(traceback.format_exc())
        print("  board invariants ABORTED:")
        print(traceback.format_exc())

    ran = [r[0] for r in RESULTS]
    expected = READONLY_CHECKS + VIEWPORT_CHECKS + BOARD_CHECKS
    if not args.url:
        expected += WRITE_CHECKS + CLOCK_CHECKS
    for name in expected:
        if name not in ran:
            check(name, False, "THIS CHECK NEVER RAN -- the run is incomplete")
    if ABORT:
        check("suite ran to completion", False,
              "ABORTED: " + ABORT[0].strip().splitlines()[-1])

    bad = [r for r in RESULTS if not r[1]]
    print()
    print("=" * 74)
    print(f"SUMMARY: {len(RESULTS) - len(bad)} passed, {len(bad)} FAILED")
    for n, _, d in bad:
        print(f"   FAILED: {n}   {d}")
    print("=" * 74)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "aborted": bool(ABORT),
            "abort_traceback": ABORT[0] if ABORT else None,
            "passed": len(RESULTS) - len(bad),
            "failed": [{"name": r[0], "detail": r[2]} for r in bad],
            "results": [{"name": r[0], "ok": r[1], "detail": r[2]} for r in RESULTS],
        }, indent=2), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
