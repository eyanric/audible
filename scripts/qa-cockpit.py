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
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# The cockpit's Enter hint is "↵ marks <player>" (U+21B5). Printing that through
# a Windows console defaulting to cp1252 raises UnicodeEncodeError *inside
# check()*, which killed the whole run at check 11 of ~82 -- on the machine the
# draft is actually run from. The suite reported a traceback instead of a
# verdict, so a green claim was never reachable here.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
        while True:
            m = json.loads(await self.ws.recv())
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


RESULTS: list[tuple[str, bool, str]] = []


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
    await bus.key("Enter", code="Enter")
    await bus.drain(1.0)
    c = await bus.snap()
    check("Enter marked the highlighted row", c["pick"] != before,
          "pick {!r} -> {!r}".format(before, c["pick"]))
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
    before = c["pick"]
    await bus.key("z", code="KeyZ", mods=2)
    await bus.drain(1.0)
    c = await bus.snap()
    check("ctrl+z undid it", c["pick"] != before, "pick {!r} -> {!r}".format(before, c["pick"]))
    before = c["pick"]
    await bus.key("u", text="u")
    await bus.drain(1.0)
    c = await bus.snap()
    check("u undid another", c["pick"] != before, "pick {!r} -> {!r}".format(before, c["pick"]))

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
            await run_suite(bus, url, readonly)
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


def start_server(league: str, port: int, state_dir: Path) -> subprocess.Popen:
    """A throwaway cockpit: real board, ISOLATED state, so QA can never touch a real draft."""
    src = REPO / "src"
    boot = "\n".join([
        f"import sys,time;sys.path.insert(0,r'{src}')",
        "from pathlib import Path",
        "import uvicorn",
        "from audible.config.loader import load_all_leagues",
        "from audible.draft.board import build_board",
        "from audible.draft.service import CockpitService",
        "from audible.server import create_app",
        f"cfg=load_all_leagues()[{league!r}]",
        f"sd=Path({str(state_dir)!r}); sd.mkdir(parents=True,exist_ok=True)",
        "[p.unlink() for p in sd.glob('*.json')]",
        "svc=CockpitService(cfg,state_dir=sd,slot_override=8)",
        "svc.board=build_board(cfg)",
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
    args = ap.parse_args()

    if args.url:
        print(f"attached to {args.url} -- READ-ONLY checks only\n")
        asyncio.run(drive(args.url.rstrip("/") + "/", readonly=True))
    else:
        port = free_port()
        with tempfile.TemporaryDirectory(prefix="audible-qa-state-") as sd:
            print(f"starting an isolated cockpit: league={args.league} "
                  f"port={port} state={sd}\n")
            proc = start_server(args.league, port, Path(sd))
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

    bad = [r for r in RESULTS if not r[1]]
    print()
    print("=" * 74)
    print(f"SUMMARY: {len(RESULTS) - len(bad)} passed, {len(bad)} FAILED")
    for n, _, d in bad:
        print(f"   FAILED: {n}   {d}")
    print("=" * 74)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
