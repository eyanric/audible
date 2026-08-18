"""Drive a real browser against the cockpit and report why it is not responding.

A page that paints but ignores you is almost always an exception thrown before the handlers
bind: the static shell is already on screen, so it looks like a working app that has stopped
listening. Inspection cannot see that. This drives an actual browser over the DevTools
protocol and reports what happened.

Run it via ``scripts/diagnose-cockpit.cmd``, which launches an ISOLATED browser first. Never
point it at a browser you are already using -- the debugging port exposes every open tab.

    python scripts/diagnose_cockpit.py --port 8080 --cdp 9444
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request

try:
    import websockets
except ImportError:  # pragma: no cover - websockets ships with the server deps
    sys.exit("needs `websockets` (it ships with the server deps): uv sync")


def find_target(cdp: int, port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{cdp}/json/list", timeout=10) as r:
        targets = json.load(r)
    wanted = f"http://127.0.0.1:{port}"
    for t in targets:
        if t.get("type") == "page" and str(t.get("url", "")).startswith(wanted):
            return t
    raise SystemExit(
        f"No browser tab is on {wanted}. Launch the browser with that URL and "
        f"--remote-debugging-port={cdp} (scripts/diagnose-cockpit.cmd does this)."
    )


PROBE = """
(async function () {
  function q(id) { return document.getElementById(id); }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function selName() {
    var s = document.querySelector('tr.sel');
    return s ? (s.querySelector('.pname') || {}).textContent : null;
  }
  var out = {};
  var best = q('bestBody');
  out.rows_rendered = best ? best.children.length : -1;
  out.grab_rows = q('grabBody') ? q('grabBody').children.length : -1;
  out.tabs_built = q('tabs') ? q('tabs').children.length : -1;
  out.controls_present = !!(q('pauseBtn') && q('undoBtn') && q('q'));

  if (!best || best.children.length === 0) {
    out.verdict = 'NO ROWS - the board never rendered; see the errors above.';
    return JSON.stringify(out);
  }

  var target = best.children[Math.min(6, best.children.length - 1)];
  var tname = (target.querySelector('.pname') || {}).textContent;
  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  out.click_moves_selection = selName() === tname;

  var sel = document.querySelector('tr.sel');
  if (sel) {
    var a = getComputedStyle(sel).backgroundColor;
    var b = getComputedStyle(best.children[best.children.length - 1]).backgroundColor;
    out.selection_is_visible = a !== b;
  }

  var btn = target.querySelector('button');
  if (!btn) {
    out.mark_button = 'MISSING';
  } else {
    var r = btn.getBoundingClientRect();
    out.mark_button_px = Math.round(r.width) + 'x' + Math.round(r.height);
    btn.click();
    await sleep(1500);
    var names = [].map.call(q('bestBody').children, function (x) {
      return (x.querySelector('.pname') || {}).textContent;
    });
    out.mark_removes_player = names.indexOf(tname) < 0;
    var u = q('undoBtn');
    if (u) {
      u.click();
      await sleep(1500);
      var after = [].map.call(q('bestBody').children, function (x) {
        return (x.querySelector('.pname') || {}).textContent;
      });
      out.undo_restores_player = after.indexOf(tname) >= 0;
    }
  }

  var p = q('pauseBtn');
  if (p) {
    var t0 = p.textContent;
    p.click();
    out.pause_responds = p.textContent !== t0;
    p.click();
  }

  out.verdict = (out.click_moves_selection && out.mark_removes_player)
    ? 'INTERACTIVE - the page responds to clicks.'
    : 'NOT INTERACTIVE - handlers are not firing.';
  return JSON.stringify(out);
})()
"""


async def run(cdp: int, port: int, seconds: float) -> int:
    target = find_target(cdp, port)
    events: list[dict] = []
    mid = 0

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
        async def call(method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if "method" in msg:
                    events.append(msg)
                if msg.get("id") == mid:
                    return msg

        for method in ("Runtime.enable", "Log.enable", "Page.enable", "Network.enable"):
            await call(method)
        await call("Page.reload", {"ignoreCache": True})

        loop = asyncio.get_event_loop()
        deadline = loop.time() + seconds
        while loop.time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
                if "method" in msg:
                    events.append(msg)
            except TimeoutError:
                pass

        print("=" * 62)
        print(" CONSOLE ERRORS AND UNCAUGHT EXCEPTIONS")
        print("=" * 62)
        problems = 0
        for m in events:
            if m["method"] == "Runtime.exceptionThrown":
                problems += 1
                d = m["params"]["exceptionDetails"]
                desc = (d.get("exception") or {}).get("description") or d.get("text")
                print(f"  EXCEPTION at line {d.get('lineNumber')}: {str(desc)[:500]}")
            elif m["method"] == "Log.entryAdded" and m["params"]["entry"].get("level") == "error":
                problems += 1
                e = m["params"]["entry"]
                print(f"  ERROR: {e.get('text')}  {e.get('url', '')}:{e.get('lineNumber', '')}")
        if not problems:
            print("  (none) -- the page initialised without throwing.")

        print()
        print("=" * 62)
        print(" FAILED NETWORK REQUESTS")
        print("=" * 62)
        fails = [m for m in events if m["method"] == "Network.loadingFailed"]
        for m in fails:
            print(f"  {m['params'].get('errorText')}")
        if not fails:
            print("  (none) -- every request the page made succeeded.")

        print()
        print("=" * 62)
        print(" INTERACTION")
        print("=" * 62)
        res = await call(
            "Runtime.evaluate",
            {"expression": PROBE, "returnByValue": True, "awaitPromise": True},
        )
        payload = res.get("result", {})
        if payload.get("exceptionDetails"):
            print("  the probe itself threw:", str(payload["exceptionDetails"])[:400])
            return 1
        raw = payload.get("result", {}).get("value")
        data = json.loads(raw) if raw else {}
        for key, value in data.items():
            if key != "verdict":
                print(f"  {key}: {value}")
        print()
        print(f"  >>> {data.get('verdict', 'no verdict')}")
        return 0 if str(data.get("verdict", "")).startswith("INTERACTIVE") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose a non-responsive cockpit.")
    parser.add_argument("--port", type=int, default=8080, help="cockpit port")
    parser.add_argument("--cdp", type=int, default=9444, help="browser debugging port")
    parser.add_argument("--settle", type=float, default=8.0, help="seconds to watch")
    args = parser.parse_args()
    return asyncio.run(run(args.cdp, args.port, args.settle))


if __name__ == "__main__":
    sys.exit(main())
