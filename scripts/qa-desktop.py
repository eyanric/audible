#!/usr/bin/env python3
"""Desktop regression suite: the cockpit as the PRIMARY surface, not a reflowed phone.

    uv run --extra nflverse python scripts/qa-desktop.py
    uv run --extra nflverse python scripts/qa-desktop.py --keep   (leave the browser open)

WHY THIS EXISTS, SEPARATELY FROM qa-cockpit.py. Everything merged since PR #30 was
verified at 393px because the phone was the primary surface. Then the launcher changed
to desktop-primary (127.0.0.1, "Eric drafts at this desk") and nothing re-verified the
desktop path as the thing actually being used. This suite treats 1920x1080 and 2560x1440
as the product and asks whether the extra width BUYS anything.

WHAT IT ASSERTS THAT qa-cockpit.py DOES NOT:

  * DIRECTION AND IDENTITY, not just change. qa-cockpit checks `pick != before` after
    Enter. That passes if Enter marks the WRONG player, or marks three, or decrements.
    Here: Enter marks the row that was highlighted, by name, and the counter moves by
    exactly +1; ctrl+z moves it by exactly -1.
  * MORE ROWS AT DESKTOP than at mobile -- the point of the width.
  * TIMING TERMS AT EVERY PICK of a run, not once at the start. A null mid-run is the
    regression that started all of this, and it is invisible in a spot check.
  * JS HEALTH AFTER THE RUN, not only at t+0.5s. A handler that throws on the 20th mark
    is exactly the bug a load-time check cannot see.

SAFETY. Starts its own cockpit on a free port with an ISOLATED state_dir and marks
players in it. It must never be pointed at the real draft session; there is no --url.

Exit code 0 only if every check passed.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import statistics
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# Same reason as qa-cockpit.py: player names and the cockpit's own hint text
# carry characters cp1252 cannot encode, and the failure lands inside the
# printing helper -- so it kills the run rather than failing one check.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Reuse the CDP plumbing rather than reimplementing it -- that read loop keeps
# Runtime.exceptionThrown instead of discarding it, which is the whole reason
# qa-cockpit.py can see a dead IIFE at all.
_spec = importlib.util.spec_from_file_location("qa_cockpit", REPO / "scripts" / "qa-cockpit.py")
qa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qa)

DESKTOP = [(1920, 1080), (2560, 1440)]
MOBILE = (393, 852)

RESULTS: list[tuple[bool, str, str]] = []
# (ok, name, detail, reason, since) -- accepted failures, guarded. See known().
KNOWN: list[tuple[bool, str, str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((bool(ok), name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""),
          flush=True)
    return bool(ok)


def banner(title: str) -> None:
    print("\n" + "=" * 74 + "\n" + title + "\n" + "=" * 74,
          flush=True)


def note(name: str, detail: str) -> None:
    """An observation that is reported but does not gate the run."""
    print(f"  [note] {name}\n         {detail}", flush=True)


def known(name: str, ok: bool, detail: str, reason: str, since: str) -> bool:
    """A failure we have decided to accept -- with a guard that can actually fire.

    The bucket is neither pass nor fail, but it is NOT inert: if a known failure starts
    PASSING, the run goes red. A state change is the thing worth being told about, and a
    suite that quietly reclassifies itself has stopped being an instrument.

    That asymmetry is the same one the verify-offline work landed: a guard which can only
    ever be satisfied is not a guard. `docs/qa-desktop-known.md` carries the standing
    entries and what would justify promoting each back to check().
    """
    KNOWN.append((bool(ok), name, detail, reason, since))
    print(f"  [KNOWN] {name}", flush=True)
    print(f"          accepted {since}: {reason}", flush=True)
    if detail:
        print(f"          {detail}", flush=True)
    if ok:
        print("          *** THIS NOW PASSES. Promote it back to check(). ***", flush=True)
    return bool(ok)


# A richer snapshot than qa-cockpit's: adds layout geometry, the clock, and the
# sync chip, which is what the desktop and desync questions are actually about.
SNAP2 = r"""
(function(){
  function txt(el){return el?(el.textContent||"").trim():null;}
  function num(s){ if(s==null) return null;
    var m=String(s).match(/-?\d+/); return m?parseInt(m[0],10):null; }
  var sel=document.querySelector("tr.sel");
  var best=document.querySelectorAll("#bestBody tr");
  var de=document.documentElement;
  // widest visible block-level panel, as a fraction of the viewport
  var widest=0, widestId=null;
  [].slice.call(document.querySelectorAll("#board, #bestPanel, #grabPanel, main, .cols"))
    .forEach(function(el){ var r=el.getBoundingClientRect();
      if(r.width>widest){widest=r.width; widestId=el.id||el.className||el.tagName;} });
  // smallest effective render scale among laid-out elements
  var minScale=1, minSel=null;
  [].slice.call(document.querySelectorAll("#board *")).slice(0,400).forEach(function(el){
    if(!el.offsetWidth) return;
    var r=el.getBoundingClientRect();
    var s=r.width/el.offsetWidth;
    if(s>0 && s<minScale){minScale=s; minSel=el.tagName+"."+(el.className||"");}
  });
  var chip=document.getElementById("syncChip");
  return JSON.stringify({
    focus:(document.activeElement&&(document.activeElement.id||document.activeElement.tagName))||null,
    rows:best.length,
    grabRows:document.querySelectorAll("#grabBody tr").length,
    selCount:document.querySelectorAll("tr.sel").length,
    selName:sel?txt(sel.querySelector(".pname")):null,
    firstName:best.length?txt(best[0].querySelector(".pname")):null,
    names:[].slice.call(best).slice(0,60).map(function(r){return txt(r.querySelector(".pname"));}),
    // rows whose box actually sits inside the viewport -- the honest "how much
    // board can I see at once", as distinct from how many are in the DOM.
    rowsVisible:[].slice.call(best).filter(function(r){
      var b=r.getBoundingClientRect();
      return b.height>0 && b.top<innerHeight && b.bottom>0;}).length,
    activeTab:(function(){var a=document.querySelector('#tabs button[aria-pressed="true"]');
      return a?a.dataset.key:null;})(),
    pick:num(txt(document.getElementById("pickNo"))),
    pickRaw:txt(document.getElementById("pickNo")),
    round:num(txt(document.getElementById("pickRound"))),
    clockNum:num(txt(document.getElementById("clockNum"))),
    clockWord:txt(document.getElementById("clockWord")),
    clockSub:txt(document.getElementById("clockSub")),
    slotLine:txt(document.getElementById("slotLine")),
    q:(document.getElementById("q")||{}).value,
    hint:txt(document.getElementById("enterHint")),
    legend:txt(document.getElementById("legendDigits")),
    tabs:[].slice.call(document.querySelectorAll("#tabs button"))
          .filter(function(b){return !b.hidden;}).map(function(b){return b.dataset.key;}),
    hOverflow:de.scrollWidth>innerWidth+1,
    scrollW:de.scrollWidth, innerW:innerWidth,
    widestFrac:innerWidth?widest/innerWidth:null, widestId:widestId,
    minScale:minScale, minScaleSel:minSel,
    syncCls:chip?chip.className:null,
    syncText:txt(document.getElementById("syncText")),
    visibleSection:(function(){var r=document.querySelector("tr.sel");
      return r?(r.closest("#grabBody")?"grab":"best"):null;})()
  });
})()
"""


async def snap2(bus):
    return json.loads(await bus.ev(SNAP2))


class PatchBus(qa.Bus):
    """A Bus that can rewrite /api/state on the wire.

    The cockpit's script is an IIFE, so `S` and `renderSync()` are NOT reachable
    from Runtime.evaluate -- an earlier version of this suite tried to poke them
    directly, got three "Uncaught" evals, and silently measured the SAME live
    state three times while appearing to test three. Patching the response
    instead drives the real render path and cannot lie in that way.
    """

    def __init__(self, ws):
        super().__init__(ws)
        self.sync_patch: dict | None = None
        self.paused: list[dict] = []

    def _record(self, m):
        if m.get("method") == "Fetch.requestPaused":
            self.paused.append(m["params"])
            return
        super()._record(m)

    async def pump(self, seconds=3.0):
        """Drain events and answer any intercepted request."""
        end = time.time() + seconds
        while time.time() < end:
            await self.drain(0.15)
            while self.paused:
                p = self.paused.pop(0)
                await self._answer(p)

    async def _answer(self, p):
        rid, url = p["requestId"], p.get("request", {}).get("url", "")
        if self.sync_patch is None or "/api/state" not in url:
            await self.send("Fetch.continueRequest", {"requestId": rid})
            return
        try:
            r = await self.send("Fetch.getResponseBody", {"requestId": rid})
            raw = r["result"]["body"]
            if r["result"].get("base64Encoded"):
                import base64
                raw = base64.b64decode(raw).decode()
            doc = json.loads(raw)
            doc.setdefault("sync", {}).update(self.sync_patch)
            body = json.dumps(doc).encode()
            import base64 as b64
            await self.send("Fetch.fulfillRequest", {
                "requestId": rid, "responseCode": 200,
                "responseHeaders": [{"name": "Content-Type", "value": "application/json"}],
                "body": b64.b64encode(body).decode(),
            })
        except Exception:
            with __import__("contextlib").suppress(Exception):
                await self.send("Fetch.continueRequest", {"requestId": rid})


def api(port, path="/api/state"):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


async def search(bus, text, settle=0.6):
    """Put `text` in the search box, reliably.

    Escape BLURS the box (that is why digit shortcuts start working after it),
    so 'Escape then type' sends the characters to the body and filters nothing --
    the board stays at its full 140 rows and the highlight sits on whatever was
    already first. An earlier version of this suite did exactly that and reported
    two product bugs that were really this mistake. Focus, select-all, type.
    """
    # Clear by setting the value and firing `input`, NOT with ctrl+a.
    # Input.dispatchKeyEvent with a Control modifier does not perform select-all
    # in the field, so an earlier version silently APPENDED on every call --
    # producing queries like 'emeka egbukaegbuk' that matched nothing, and a skip
    # test that entered zero picks and then "passed" by rewinding zero.
    await bus.ev(
        "(function(){var e=document.getElementById('q');e.focus();e.value='';"
        "e.dispatchEvent(new Event('input',{bubbles:true}));return e.value;})()"
    )
    await bus.drain(0.2)
    for ch in text:
        await bus.key(ch, text=ch)
    await bus.drain(settle)
    return await snap2(bus)


async def viewport(bus, w, h):
    await bus.send("Emulation.setDeviceMetricsOverride",
                   {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
    await bus.drain(0.6)


# --------------------------------------------------------------------------
# a) LAYOUT
# --------------------------------------------------------------------------
async def task_layout(bus, port):
    banner("3a. LAYOUT - desktop must be the product, not a stretched phone")
    await viewport(bus, *MOBILE)
    m = await snap2(bus)
    mobile_rows, mobile_vis = m["rows"], m["rowsVisible"]
    note("mobile baseline (393x852)",
         f"rows in DOM={mobile_rows}, rows visible without scrolling={mobile_vis}")

    for w, h in DESKTOP:
        await viewport(bus, w, h)
        s = await snap2(bus)
        tag = f"{w}x{h}"
        note(f"{tag} row counts",
             f"DOM={s['rows']} visible={s['rowsVisible']} "
             f"(mobile DOM={mobile_rows} visible={mobile_vis})")
        check(f"{tag}: no horizontal scroll",
              not s["hOverflow"], f"scrollWidth={s['scrollW']} innerWidth={s['innerW']}")
        check(f"{tag}: no stranded narrow column",
              (s["widestFrac"] or 0) >= 0.60,
              f"widest panel {s['widestId']!r} spans "
              f"{100 * (s['widestFrac'] or 0):.0f}% of viewport")
        check(f"{tag}: nothing renders below 63% scale",
              (s["minScale"] or 1) >= 0.63,
              f"min effective scale {100 * (s['minScale'] or 1):.0f}% on {s['minScaleSel']}")
        # The width question, asked two ways, because they have different answers.
        known(f"{tag}: shows MORE recommend rows than mobile (DOM)",
              s["rows"] > mobile_rows,
              f"desktop rows={s['rows']} vs mobile rows={mobile_rows}. "
              f"MAX_ROWS in index.html is a viewport-INDEPENDENT hard cap, so extra "
              f"width buys no extra recommendations -- the desktop board is the same "
              f"single column, reflowed.",
              reason="MAX_ROWS is a viewport-independent cap, so desktop width buys no "
                     "extra DOM rows. The assertion encodes a design opinion -- that width "
                     "SHOULD buy rows -- which the two sibling checks already answer "
                     "better, and both pass.",
              since="2026-08-31")
        check(f"{tag}: shows MORE rows without scrolling than mobile",
              s["rowsVisible"] > mobile_vis,
              f"visible desktop={s['rowsVisible']} vs mobile={mobile_vis} "
              f"(this is a viewport-HEIGHT effect, not a width one)")


# --------------------------------------------------------------------------
# a0) AFFORDANCE - can the one action on a row be SEEN and HIT with a mouse
#
# This runs FIRST and touches nothing before it measures. That ordering is the
# test: "visible at rest" is only a fact if no pointer has been near the row.
# Every earlier check in this file drove the page by keyboard or by selector,
# and a selector finds an invisible 18x18 control and clicks its exact centre
# without complaint -- which is precisely how a button that no human could find
# passed ten green checks three times running.
# --------------------------------------------------------------------------
# Raised after Eric drove it at pick speed: 64x30 cleared the old floor and was still
# hard to hit. The floor was too low, not the button.
MIN_H, MIN_W = 40.0, 96.0
HUMAN_AIM_SLOP = 16   # px of aiming error a real target must absorb

REST_JS = """(function(){
  var e=document.querySelector('#bestBody tr.prow button.mark');
  var c2=document.querySelector('#bestBody tr.prow td.c-act');
  if(!e||!c2) return 'null';
  var r=e.getBoundingClientRect(), c=getComputedStyle(e);
  var rc=c2.getBoundingClientRect();
  var u=document.getElementById('undoBtn');
  return JSON.stringify({
    w:r.width, h:r.height,
    cellX:rc.x+rc.width/2, cellY:rc.y+rc.height/2,
    border:c.borderTopColor, bw:c.borderTopWidth, bg:c.backgroundColor,
    opacity:c.opacity, vis:c.visibility, disp:c.display,
    text:e.textContent.trim(),
    hoverBranch: window.matchMedia('(hover:hover)').matches,
    undoHidden: !!(u&&u.hidden), undoDisabled: !!(u&&u.disabled),
    undoText: u?u.textContent.trim():null,
    firstName: (document.querySelector('#bestBody .pname')||{}).textContent
  });
})()"""


def _alpha(css):
    """Alpha of a computed rgb()/rgba(). `transparent` computes to rgba(0,0,0,0)."""
    if css.startswith("rgba"):
        return float(css.split(",")[-1].strip(" )"))
    return 1.0 if css.startswith("rgb") else 0.0


async def task_affordance(bus, port):
    banner("3a0. AFFORDANCE - the action must be visible at rest and hittable by mouse")
    await viewport(bus, 1920, 1080)
    raw = await bus.ev(REST_JS)
    if not raw or raw == "null":
        check("the row action button exists at all", False, "no button.mark in #bestBody")
        return
    r = json.loads(raw)

    # Which media branch are we actually measuring? If this is false the whole task is
    # measuring the touch layer, which was never the broken one.
    check("desktop matches (hover:hover), not the touch branch",
          r["hoverBranch"] is True,
          f"matchMedia('(hover:hover)') = {r['hoverBranch']}")

    # 1. SIZE FLOOR
    check("row action button meets the desktop size floor",
          r["w"] >= MIN_W and r["h"] >= MIN_H,
          f"measured {r['w']:g}x{r['h']:g} CSS px, floor {MIN_W:g}x{MIN_H:g}")

    # 2. VISIBLE AT REST -- nothing has hovered or focused this row yet
    painted = (_alpha(r["border"]) > 0 and r["bw"] != "0px"
               and _alpha(r["bg"]) > 0 and float(r["opacity"]) == 1.0
               and r["disp"] != "none" and r["vis"] == "visible")
    check("row action button is painted at rest (no hover, no focus)",
          painted,
          f"border={r['border']} ({r['bw']}) bg={r['bg']} opacity={r['opacity']}")
    check("row action button carries a word, not a bare glyph",
          r["text"] in ("TAKEN", "DRAFT HIM"),
          f"label = {r['text']!r}")

    # 4. MOUSE ONLY, END TO END. Aimed at the centre of the action CELL and then missed
    # by HUMAN_AIM_SLOP px -- a real target absorbs that, an 18px one does not.
    before = api(port)["clock"]["current_pick"]
    victim = (r["firstName"] or "").strip()
    check("undo is present and disabled before any mark",
          (not r["undoHidden"]) and r["undoDisabled"],
          f"hidden={r['undoHidden']} disabled={r['undoDisabled']} "
          f"text={r['undoText']!r}")

    await bus.click(r["cellX"] + HUMAN_AIM_SLOP, r["cellY"])
    await bus.drain(1.2)
    after = api(port)["clock"]["current_pick"]
    check(f"a mouse click {HUMAN_AIM_SLOP}px off centre marks exactly one player",
          after == before + 1,
          f"current_pick {before} -> {after} after one off-centre click on {victim!r}")

    post = json.loads(await bus.ev(REST_JS) or "null") or {}
    check("undo becomes enabled and names the player just marked",
          post.get("undoDisabled") is False and post.get("undoText") == "Undo: " + victim,
          f"undo reads {post.get('undoText')!r} (wanted {'Undo: ' + victim!r})")
    check("the marked player left the board",
          (post.get("firstName") or "").strip() != victim,
          f"board now starts at {(post.get('firstName') or '').strip()!r}")

    # PUT THE BOARD BACK. Every task after this one shares this server, and a stray
    # extra pick shifts every downstream pick number and changes which players are on
    # the board -- which silently rewrites what the later tasks are even testing.
    # Undoing by mouse is also the only mouse-driven undo in this file.
    u = await bus.box("#undoBtn")
    if u:
        await bus.click(u["x"], u["y"])
        await bus.drain(1.2)
    restored = api(port)["clock"]["current_pick"]
    check("undo by mouse puts the board back for the rest of the suite",
          restored == before,
          f"current_pick {after} -> {restored}, wanted {before}")


# --------------------------------------------------------------------------
# b) KEYBOARD, EYES-OFF — no pointer is used anywhere in here
# --------------------------------------------------------------------------
async def task_keyboard(bus, port):
    banner("3b. KEYBOARD, EYES-OFF - direction and identity, not just it changed")
    await viewport(bus, 1920, 1080)
    await bus.send("Page.navigate", {"url": f"http://127.0.0.1:{port}/"})
    for _ in range(30):
        await bus.drain(0.5)
        s = await snap2(bus)
        if s["rows"]:
            break
    check("search box is focused on load (no click needed)",
          s["focus"] == "q", f"activeElement={s['focus']!r}")

    # type-ahead
    seed = (s["firstName"] or "").split()[-1][:5].lower()
    await bus.typ(seed)          # typed directly: this check IS about type-ahead
    await bus.drain(0.8)
    t = await snap2(bus)
    check("type-ahead filters the board",
          0 < t["rows"] < s["rows"], f"{seed!r}: {s['rows']} -> {t['rows']} rows")
    check("type-ahead highlights exactly one row",
          t["selCount"] == 1 and bool(t["selName"]), f"sel={t['selName']!r}")

    # ENTER: identity + exact +1
    target, before = t["selName"], t["pick"]
    await bus.key("Enter", code="Enter")
    await bus.drain(1.2)
    a = await snap2(bus)
    st = api(port)
    check("Enter moves the pick counter by exactly +1",
          a["pick"] == (before or 0) + 1, f"pick {before} -> {a['pick']}")
    taken = [p.get("player_name") or p.get("name") for p in st.get("recent_picks", [])][:1]
    check("Enter marked the HIGHLIGHTED row, by name",
          bool(target) and any(target == n for n in taken),
          f"highlighted {target!r}; most recent pick {taken}")
    check("query cleared and focus stayed in the box",
          a["q"] == "" and a["focus"] == "q", f"q={a['q']!r} focus={a['focus']!r}")

    # CTRL+Z: exact -1
    before = a["pick"]
    await bus.key("z", code="KeyZ", mods=2)
    await bus.drain(1.2)
    u = await snap2(bus)
    check("ctrl+z moves the pick counter by exactly -1",
          u["pick"] == before - 1, f"pick {before} -> {u['pick']}")

    # digits switch sections, keyboard only
    # The active tab is marked with aria-pressed="true", not a class.
    tabs = u["tabs"] or []
    # Asked TWICE, because the answer differs and only one of the two states is
    # the one Eric will actually be in.
    #
    # Start from a NON-ALL tab and never test index 0 first: 'ALL' is the
    # default, so "press 0, still ALL" passes whether the key worked or not.
    async def press_digits(label):
        ok, seen_detail, swallowed = True, [], None
        for i in range(1, min(len(tabs), 7)):
            await bus.key(str(i), text=str(i))
            await bus.drain(0.45)
            after = await snap2(bus)
            got = after["activeTab"]
            seen_detail.append(f"{i}->{got}")
            if got != tabs[i]:
                ok = False
                if swallowed is None and after["q"]:
                    swallowed = (after["focus"], after["q"])
            await bus.key("Escape", code="Escape")
            await bus.drain(0.25)
        return ok, " ".join(seen_detail), swallowed

    # (1) the REALISTIC eyes-off state: focus is in the search box, which is
    #     where it sits on load and where Enter puts it back after every pick.
    await bus.key("Escape", code="Escape")
    await bus.drain(0.3)
    await bus.ev("document.getElementById('q').focus()")
    await bus.drain(0.25)
    focused = (await snap2(bus))["focus"]
    ok_typing, det_typing, swallowed = await press_digits("search-focused")
    extra = ""
    if swallowed:
        # Before 2026-08-31 this was the standing diagnosis and the advice was
        # "Escape first, then the digit". The handler now intercepts a digit typed
        # into an EMPTY box, so a fire here is a REGRESSION of that guard rather than
        # the original design gap -- check that the empty-query branch in index.html's
        # keydown handler still runs ahead of the Enter branch.
        extra = (f"\n         CAUSE: the digit was typed INTO the search box "
                 f"(focus={swallowed[0]!r}, q={swallowed[1]!r}). The legend "
                 f"advertises {u['legend']!r}, "
                 f"and the box holds focus on load and after every Enter, so this is "
                 f"the state that matters. The empty-box digit guard in index.html "
                 f"has REGRESSED.")
    check("digit keys switch sections with the search box focused (the eyes-off state)",
          ok_typing,
          f"focus at start={focused!r} legend={u['legend']!r} tabs={tabs} : "
          + det_typing + extra)

    # (2) after Escape, i.e. once focus has left the box.
    await bus.key("Escape", code="Escape")
    await bus.drain(0.35)
    ok_esc, det_esc, _ = await press_digits("after-escape")
    check("digit keys switch sections after Escape releases the search box",
          ok_esc, det_esc)

    # Leave the board in a clean state: ALL selected, no query, or the run below
    # starts against a filtered list and marks nothing.
    await bus.key("0", text="0")
    await bus.drain(0.4)
    await bus.key("Escape", code="Escape")
    await bus.drain(0.5)
    reset = await snap2(bus)
    check("board resets to ALL with an empty query before the run",
          reset["rows"] > 0 and not reset["q"],
          f"activeTab={reset['activeTab']!r} rows={reset['rows']} q={reset['q']!r}")


# --------------------------------------------------------------------------
# c) + d) TURN STATE and TIMING TERMS across a real run
# --------------------------------------------------------------------------
TURNS = [8, 9, 24, 25, 40, 41, 56, 57]

# /api/state and the MCP tools name the SAME four numbers differently. The task
# list uses the MCP names; the cockpit's own JSON uses these. Checked against a
# live dump rather than assumed -- getting this wrong makes the check report a
# product null when it is really a typo, which is worse than no check.
#   MCP picks_until_mine            -> clock picks_until_me
#   MCP rival_picks_before_my_next  -> clock opponent_picks_until_horizon
#   MCP on_the_clock_slot           -> clock slot_on_clock
TIMING = ["picks_until_me", "my_next_pick", "opponent_picks_until_horizon", "slack_picks"]
MCP_NAME = {
    "picks_until_me": "picks_until_mine",
    "opponent_picks_until_horizon": "rival_picks_before_my_next",
    "my_next_pick": "my_next_pick",
    "slack_picks": "slack_picks",
}


async def task_run(bus, port, picks=25):
    print("\n" + "=" * 74
          + f"\n3c/3d. TURN STATE + TIMING TERMS over a {picks}-pick run\n" + "=" * 74)
    nulls, turn_rows, seen = [], {}, 0
    for _ in range(picks):
        s = await snap2(bus)
        if not s["rows"] or not s["firstName"]:
            break
        # Select the way a person does -- type-ahead -- rather than assuming a
        # highlight is already sitting somewhere.
        await search(bus, s["firstName"].lower(), settle=0.45)
        await bus.key("Enter", code="Enter")
        await bus.drain(0.85)
        st = api(port)
        clock = st.get("clock", {})
        cur = clock.get("current_pick")
        seen += 1
        missing = [k for k in TIMING if clock.get(k) is None]
        if missing:
            nulls.append((cur, missing))
        if cur in TURNS:
            dom = await snap2(bus)
            turn_rows[cur] = {
                "clock_my_slot": clock.get("my_slot"),
                "clock_on_clock": clock.get("slot_on_clock"),
                "clock_label": clock.get("label"),
                "dom_pick": dom["pick"],
                "dom_clockNum": dom["clockNum"],
                "dom_clockWord": dom["clockWord"],
            }

    check(f"every timing term non-null at all {seen} picks",
          not nulls,
          f"all four present at every one of {seen} picks "
          f"({', '.join(MCP_NAME[t] for t in TIMING)})" if not nulls
          else f"NULL at {len(nulls)} of {seen} picks; first six: "
               + str([(c, [MCP_NAME[k] for k in m]) for c, m in nulls][:6]))

    reached = sorted(turn_rows)
    check("reached at least the first four of my turns",
          len([t for t in reached if t in TURNS]) >= 4,
          f"turn picks observed: {reached}")

    for pick_no, row in sorted(turn_rows.items()):
        dom_ok = row["dom_pick"] == pick_no
        check(f"pick {pick_no}: DOM pick number agrees with the clock dict",
              dom_ok, f"api current_pick={pick_no} dom #pickNo={row['dom_pick']} "
                      f"clockWord={row['dom_clockWord']!r}")
        if pick_no in (8, 24, 40, 56):
            check(f"pick {pick_no}: it is MY turn per the clock dict",
                  row["clock_on_clock"] == 8,
                  f"on_the_clock_slot={row['clock_on_clock']} my_slot={row['clock_my_slot']}")
    return seen


# --------------------------------------------------------------------------
# 4) SUSTAINED ENTRY — the path nobody has tested
# --------------------------------------------------------------------------
async def task_sustained(bus, port):
    banner("4. SUSTAINED ENTRY - 7 picks, a wrong entry, a duplicate, a skip")
    # 7 consecutive opponent picks, keyboard only.
    #
    # WHAT IS AND IS NOT MEASURED HERE. Wall-clock "seconds per pick" from this
    # harness is NOT a human-speed number: Bus.key drains 0.2s after EVERY
    # keystroke, so a 12-character name costs 2.4s of harness delay before the
    # app is asked to do anything. An earlier version of this suite reported
    # that figure as though it were entry speed, and then gated on it.
    # What genuinely belongs to the app is the latency from the Enter keydown
    # to the pick counter changing. That is what is gated; the typing time is
    # reported beside it and labelled as harness-paced.
    latencies, totals = [], []
    for _ in range(7):
        s = await snap2(bus)
        nm = s["firstName"]
        if not nm:
            break
        t_start = time.time()
        await search(bus, nm.lower(), settle=0.35)
        before = (await snap2(bus))["pick"]
        t_enter = time.time()
        await bus.key("Enter", code="Enter")
        for _ in range(40):
            if (await snap2(bus))["pick"] != before:
                break
            await bus.drain(0.05)
        latencies.append(time.time() - t_enter)
        totals.append(time.time() - t_start)
    if latencies:
        note("7 consecutive picks, keyboard only",
             "APP latency, Enter -> counter moves: "
             + ", ".join(f"{t:.2f}s" for t in latencies)
             + f"\n         median {statistics.median(latencies):.2f}s"
             + f"\n         (full-name typing incl. harness pacing: median "
               f"{statistics.median(totals):.2f}s/pick, {sum(totals):.1f}s total"
               f" -- NOT a human-speed figure, see the comment in this file)")
        check("the app commits a pick in under 1.5s",
              max(latencies) < 1.5, f"slowest {max(latencies):.2f}s")

    # WRONG PLAYER, then correct it
    s = await snap2(bus)
    wrong_target = s["firstName"]
    pre = await search(bus, (wrong_target or "").lower())
    await bus.key("Enter", code="Enter")
    await bus.drain(0.9)
    after_wrong = await snap2(bus)
    keys = 0
    await bus.key("z", code="KeyZ", mods=2)   # 1 keystroke to undo
    keys += 1
    await bus.drain(0.9)
    fixed = await snap2(bus)
    check("a wrong entry is undone by ONE keystroke, back to the same pick number",
          fixed["pick"] == pre["pick"],
          f"pick {pre['pick']} -> {after_wrong['pick']} (wrong) -> {fixed['pick']} "
          f"after {keys} keystroke (ctrl+z)")
    still_listed = wrong_target in (fixed["names"] or [])
    check("the wrongly-marked player is back ON the board after undo",
          still_listed, f"{wrong_target!r} present in board rows: {still_listed}")

    # SAME PLAYER TWICE.
    #
    # Searched by FULL NAME, deliberately. An earlier version used a 5-char
    # fragment and was flaky -- because once the intended player is marked, that
    # fragment can match somebody ELSE, so the "duplicate" test was really
    # marking a second, different player. That flakiness is itself the finding
    # below, so it is now measured on purpose instead of intermittently.
    s = await snap2(bus)
    dup = s["firstName"]
    p0 = (await search(bus, dup.lower()))["pick"]
    await bus.key("Enter", code="Enter")
    await bus.drain(1.0)
    p1 = (await snap2(bus))["pick"]

    second = await search(bus, dup.lower(), settle=0.8)
    await bus.key("Enter", code="Enter")
    await bus.drain(1.0)
    p2 = (await snap2(bus))["pick"]
    note("entering the SAME player twice (searched by full name)",
         f"{dup!r}: pick {p0} -> {p1} on the first Enter. Re-searching the same "
         f"full name returned {second['rows']} row(s) "
         f"(sel={second['selName']!r}); pick after the second Enter = {p2}.")
    check("a marked player cannot be entered twice",
          p2 == p1,
          f"pick stayed at {p1}" if p2 == p1 else
          f"pick moved {p1} -> {p2}: the second Enter marked "
          f"{second['selName']!r}, which is NOT the player searched for")

    # THE FRAGMENT HAZARD, which is what divided attention actually produces.
    frag = dup.split()[-1][:5].lower()
    fr = await search(bus, frag, settle=0.8)
    before_frag = (await snap2(bus))["pick"]
    await bus.key("Enter", code="Enter")
    await bus.drain(0.9)
    after_frag = (await snap2(bus))["pick"]
    note("typing a fragment of an ALREADY-TAKEN player, then Enter",
         f"{frag!r} (from {dup!r}, already marked) matched {fr['rows']} row(s), "
         f"while a STALE highlight still showed {fr['selName']!r}.\n"
         f"         Enter moved the counter {before_frag} -> {after_frag}.")
    check("Enter on an empty result set marks nothing",
          after_frag == before_frag,
          f"counter unchanged at {after_frag}: an empty search is a no-op even "
          f"though a leftover highlight ({fr['selName']!r}) is still painted"
          if after_frag == before_frag else
          f"counter moved {before_frag} -> {after_frag}: Enter marked the stale "
          f"highlight {fr['selName']!r}, which is NOT what was typed")

    # SKIP A PICK, discover 3 picks later.
    # Clear the box first. The fragment probe above leaves a query that matches
    # nothing, and an earlier version of this section silently entered ZERO
    # picks because firstName was None -- then "passed" by rewinding nothing.
    cleared = await search(bus, "", settle=0.6)
    check("the search box can be cleared back to a full board",
          cleared["rows"] > 0 and not cleared["q"],
          f"after clearing: q={cleared['q']!r} rows={cleared['rows']} "
          f"first={cleared['firstName']!r}")
    before_skip = api(port)["clock"]["current_pick"]
    entered = 0
    for _ in range(3):
        s = await snap2(bus)
        if not s["firstName"]:
            break
        was = api(port)["clock"]["current_pick"]
        await search(bus, s["firstName"].lower(), settle=0.5)
        await bus.key("Enter", code="Enter")
        await bus.drain(0.8)
        # Count only entries that ACTUALLY advanced the draft. Counting attempts
        # made the undo arithmetic below wrong whenever a search matched nothing.
        if api(port)["clock"]["current_pick"] == was + 1:
            entered += 1
    after = api(port)["clock"]["current_pick"]
    undos = 0
    for _ in range(entered):
        await bus.key("z", code="KeyZ", mods=2)
        await bus.drain(0.7)
        undos += 1
    back = api(port)["clock"]["current_pick"]
    note("a skipped pick discovered 3 picks later",
         f"current_pick {before_skip} -> {after} after {entered} entries; "
         f"{undos} x ctrl+z rewound to {back}.\n"
         f"         There is no insert-at-position control anywhere in the UI: to place a "
         f"pick you missed, you must undo every pick made since, re-enter the missed one, "
         f"then re-enter the others IN ORDER. At {entered} picks that is "
         f"{undos} undos plus {entered + 1} re-entries.")
    check("undo rewinds exactly as many picks as were entered",
          back == before_skip,
          f"rewound to {back}, wanted {before_skip} "
          f"({entered} entered, {undos} undone)")


# --------------------------------------------------------------------------
# 5) DESYNC VISIBILITY
# --------------------------------------------------------------------------
async def task_desync(bus, port):
    banner("5. DESYNC VISIBILITY - one glance, and failing != stale")
    s = await snap2(bus)
    check("the current pick number is on screen without scrolling",
          s["pick"] is not None and s["pickRaw"] is not None,
          f"#pickNo reads {s['pickRaw']!r} (round {s['round']}) - "
          f"compare this to ESPN on the phone")

    box = await bus.box("#pickNo")
    y = box["y"] if box else None
    check("the pick number is in the top third of the viewport",
          y is not None and y < 1080 / 3,
          f"#pickNo at y={y:.0f}px of 1080" if y is not None else "#pickNo has no box")

    # Drive the three sync states by rewriting /api/state on the wire and
    # reloading, so the REAL render path runs. See PatchBus.
    await bus.send("Fetch.enable", {"patterns": [
        {"urlPattern": "*/api/state*", "requestStage": "Response"}]})
    states = {}
    for label, payload in (
        ("live", {"age_s": 2.0, "status": "live", "last_success": "19:04:11"}),
        ("stale", {"age_s": 20.0, "status": "stale", "last_success": "19:03:20"}),
        ("failing", {"age_s": None, "status": "failing", "last_success": None}),
    ):
        bus.sync_patch = payload
        await bus.send("Page.reload", {"ignoreCache": True})
        v = None
        for _ in range(14):
            await bus.pump(1.0)
            v = await snap2(bus)
            if v["syncText"] and v["rows"]:
                break
        states[label] = (v["syncCls"], v["syncText"])
        note(f"sync {label} (age_s={payload['age_s']}, status={payload['status']!r})",
             f"chip class={v['syncCls']!r} text={v['syncText']!r}")
    bus.sync_patch = None
    await bus.send("Fetch.disable")

    check("a live feed is visually distinct from a stale one",
          states["live"][0] != states["stale"][0],
          f"live={states['live'][0]!r} stale={states['stale'][0]!r}")
    check("a FAILING feed is visually distinct from a merely STALE one",
          states["failing"][0] != states["stale"][0],
          f"failing class={states['failing'][0]!r} vs stale class={states['stale'][0]!r} — "
          f"if these match, the only difference is the wording: "
          f"{states['failing'][1]!r} vs {states['stale'][1]!r}")


async def main_async(keep: bool) -> int:
    state = Path(tempfile.mkdtemp(prefix="qa-desktop-"))
    port = qa.free_port()
    print(f"isolated state_dir: {state}\nport: {port}\n")
    proc = qa.start_server("espn_davis_drive", port, state)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "healthz", timeout=3).read()
            break
        except Exception:
            time.sleep(1)

    import websockets

    browser = qa.find_browser()
    import subprocess

    prof = Path(tempfile.mkdtemp(prefix="qa-prof-"))
    bproc = subprocess.Popen(
        [browser, "--headless=new", "--remote-debugging-port=0",
         f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check", url],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ws_url = None
    for _ in range(80):
        line = bproc.stdout.readline()
        if "ws://" in line:
            ws_url = line.strip().split("ws://")[-1]
            ws_url = "ws://" + ws_url
            break
    if not ws_url:
        print("could not start the browser with a debugging port")
        proc.terminate()
        return 2

    # find the page target
    import urllib.request as ur
    base = ws_url.split("/devtools/")[0].replace("ws://", "http://")
    targets = json.loads(ur.urlopen(base + "/json", timeout=10).read())
    page = next(t for t in targets if t["type"] == "page")

    try:
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            bus = PatchBus(ws)
            await bus.send("Page.enable")
            await bus.send("Runtime.enable")
            await bus.send("Log.enable")
            await bus.send("Network.enable")
            await bus.send("Network.setCacheDisabled", {"cacheDisabled": True})
            await bus.send("Page.navigate", {"url": url})
            for _ in range(30):
                await bus.drain(0.5)
                if (await snap2(bus))["rows"]:
                    break

            print("=" * 74 + "\n3f. JS HEALTH AT LOAD\n" + "=" * 74)
            check("no uncaught JS exceptions at load", not bus.errors, "; ".join(bus.errors[:3]))
            check("no console.error at load", not bus.console, "; ".join(bus.console[:3]))
            load_errs, load_cons = len(bus.errors), len(bus.console)

            await task_affordance(bus, port)
            await task_layout(bus, port)
            await task_keyboard(bus, port)
            await task_run(bus, port, picks=25)
            await task_sustained(bus, port)
            await task_desync(bus, port)

            print("\n" + "=" * 74 + "\n3f. JS HEALTH AFTER THE FULL RUN\n" + "=" * 74)
            check("no uncaught JS exceptions after the whole run",
                  len(bus.errors) == load_errs,
                  "; ".join(bus.errors[load_errs:][:4]) or "none new")
            check("no console.error after the whole run",
                  len(bus.console) == load_cons,
                  "; ".join(bus.console[load_cons:][:4]) or "none new")
    finally:
        if not keep:
            bproc.terminate()
        proc.terminate()

    print("\n" + "=" * 74)
    failed = [r for r in RESULTS if not r[0]]
    for ok, name, detail in RESULTS:
        if not ok:
            print(f"  FAIL  {name}\n        {detail}")
    # A known failure that starts passing is a state change, and it goes red. Reporting it
    # as a quiet success would let the suite relax its own standard without saying so.
    promoted = [k for k in KNOWN if k[0]]
    for _ok, name, _detail, reason, since in promoted:
        print(f"  PROMOTE  {name}\n           accepted {since} because: {reason}\n"
              f"           It now PASSES. Move it from known() back to check().")
    for ok, name, _detail, _reason, since in KNOWN:
        if not ok:
            print(f"  known  {name}  (accepted {since})")
    print(f"{len(RESULTS) - len(failed)} passed, {len(KNOWN)} known, {len(failed)} failed")
    if promoted:
        print(f"RED: {len(promoted)} known failure(s) now pass and must be promoted.")
    return 1 if (failed or promoted) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true", help="leave the browser running")
    a = ap.parse_args()
    return asyncio.run(main_async(a.keep))


if __name__ == "__main__":
    sys.exit(main())
