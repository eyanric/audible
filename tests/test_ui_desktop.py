"""Desktop affordance: can the cockpit be DRIVEN with a mouse, not merely rendered.

WHY THIS EXISTS. The P0 "make the mark button a real target" fix shipped entirely inside
`@media (hover:none)`. A mouse-driven desktop matches `hover:hover`, so none of it applied
and the one action on each row stayed an 18x18 glyph with a TRANSPARENT border in a 24px
column, revealed only once the pointer was already on the row. Every string-assertion test
in test_server.py passed against that page, and so would any browser test that drives the
control by selector -- a selector always finds an invisible 18x18 button and clicks its
exact centre without complaint. That is the gap this file closes: it asserts COMPUTED
GEOMETRY and COMPUTED PAINT at rest, and it drives the page with real mouse coordinates.

The suite is deliberately offline and deterministic: a synthetic 200-player board, an
isolated state_dir, and a real uvicorn on a free port. It never touches a real draft.

    uv run pytest tests/test_ui_desktop.py

AUDIBLE_UI_REQUIRED=1 (the default here) makes a missing browser a FAILURE rather than a
skip -- a UI suite that silently runs nothing is how this class of bug survived three
reports.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

UI_REQUIRED = os.environ.get("AUDIBLE_UI_REQUIRED", "1") == "1"

try:
    from playwright.sync_api import Page, sync_playwright
except ImportError as exc:  # pragma: no cover - environment problem, not a code path
    if UI_REQUIRED:
        raise RuntimeError(
            "playwright is not installed and AUDIBLE_UI_REQUIRED=1. "
            "Run: uv sync --group dev && uv run playwright install chromium"
        ) from exc
    pytest.skip("playwright unavailable", allow_module_level=True)


# ---------------------------------------------------------------------------------------
# THE FLOORS. A desktop control below these is one a human cannot reliably acquire.
# ---------------------------------------------------------------------------------------
# Raised after Eric drove it at pick speed: 64x30 cleared the old floor and was still
# hard to hit under time pressure. The floor was too low, not the button.
MIN_H = 40.0
MIN_W = 96.0

# How far off the centre of the action cell a human may land and still hit the control.
# This is the number that separates a real target from a pixel-hunt: the fixed button is
# >=96px wide, so 16px of aiming error is comfortably inside it; the pre-fix button was
# 18px wide in a 24px column, so the same 16px lands on empty table cell.
HUMAN_AIM_SLOP = 16

DESKTOP = {"width": 1920, "height": 1080}

# League B, seat 8 of 8. Snake: pick 8 IS slot 8, so seven picks made puts the clock on me.
ON_THE_CLOCK_PICKS = 7  # -> clock.picks_until_me == 0 -> button reads DRAFT
NOT_MY_TURN_PICKS = 0  # -> clock.picks_until_me == 7 -> button reads TAKEN

BOOT = """
import sys, time
sys.path.insert(0, r"{src}")
from pathlib import Path
import uvicorn
import audible.server.app as app_mod
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

# Serve an ALTERNATE index.html when one is given. `index()` reads the module global at
# request time, so rebinding it here is enough -- nothing under src/ is modified.
_alt = r"{index}"
if _alt:
    app_mod.INDEX = Path(_alt)

cfg = load_all_leagues()["espn_davis_drive"]
sd = Path(r"{state}"); sd.mkdir(parents=True, exist_ok=True)
[p.unlink() for p in sd.glob("*.json")]
svc = CockpitService(cfg, state_dir=sd, slot_override=8)
svc.board = DraftBoard("espn_davis_drive", [entry(i) for i in range(1, 201)])
svc.session.draft_id = "uitest"
svc.session.draft_status = "{status}"
svc.session.slot, svc.session.slot_source = 8, "override"
svc.health.last_success = time.time()
svc.session.picks = [
    Pick(pick_no=n, round=(n - 1) // TEAMS + 1, draft_slot=slot_of(n),
         player_id="p%03d" % n)
    for n in range(1, {picks} + 1)
]
uvicorn.run(create_app(svc, warm=False), host="127.0.0.1", port={port},
            log_level="warning")
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Cockpit:
    url: str
    proc: subprocess.Popen

    def state(self) -> dict:
        with urllib.request.urlopen(self.url + "/api/state", timeout=5) as r:
            return json.loads(r.read().decode())


def _boot(
    tmp: Path, picks: int, index_html: Path | None = None, status: str = "drafting"
) -> Iterator[Cockpit]:
    port = _free_port()
    script = BOOT.format(
        src=SRC, state=tmp, picks=picks, port=port, status=status,
        index=str(index_html) if index_html else "",
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script], cwd=REPO,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        if proc.poll() is not None:
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            raise RuntimeError(f"cockpit died on boot:\n{out}")
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=1):
                break
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.25)
    else:
        proc.terminate()
        raise RuntimeError("cockpit did not come up")
    try:
        yield Cockpit(url, proc)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


# ---------------------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:  # the browser binary, not the package, is missing
            msg = "\n".join([
                f"could not launch Chromium: {exc}",
                "The playwright PACKAGE installs without the browser it drives. Run:",
                "    uv run playwright install --with-deps chromium",
                "In CI this is the 'playwright browser' step in .github/workflows/ci.yml.",
            ])
            if UI_REQUIRED:
                # Loud on purpose. A UI suite that passes by running nothing is the exact
                # failure mode AUDIBLE_UI_REQUIRED exists to prevent.
                pytest.fail(msg, pytrace=False)
            pytest.skip(msg)
        try:
            yield b
        finally:
            b.close()


def _page(browser, url: str):
    """A DESKTOP page: a real viewport and, critically, has_touch=False.

    has_touch is the whole point. With touch on, the page matches `@media (hover:none)`
    and the test would measure the touch layer -- which was never broken -- while the
    desktop branch it is supposed to cover goes unexercised.
    """
    ctx = browser.new_context(viewport=DESKTOP, has_touch=False)
    page = ctx.new_page()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("#bestBody tr.prow", timeout=20_000)
    page.wait_for_function(
        "() => document.querySelectorAll('#bestBody tr.prow button.mark').length > 0",
        timeout=20_000,
    )
    return page, ctx


@pytest.fixture(scope="module")
def live(tmp_path_factory, browser):
    """The clock is NOT on me: seven picks still to come before seat 8."""
    tmp = tmp_path_factory.mktemp("ui-live")
    for cp in _boot(tmp, NOT_MY_TURN_PICKS):
        page, ctx = _page(browser, cp.url)
        try:
            yield page, cp
        finally:
            ctx.close()


@pytest.fixture(scope="module")
def on_the_clock(tmp_path_factory, browser):
    """The clock IS on me -- pressing the row action records MY pick."""
    tmp = tmp_path_factory.mktemp("ui-clock")
    for cp in _boot(tmp, ON_THE_CLOCK_PICKS):
        page, ctx = _page(browser, cp.url)
        try:
            yield page, cp
        finally:
            ctx.close()


# The pre-fix page, pinned to the IMMUTABLE git blob rather than a branch.
# It anchored on `main` once, and the moment PR #39 merged, `main` BECAME the fixed page --
# so the control compared the fix against itself, found 0 failures where it demands 3, and
# turned CI red. A negative control must never anchor to a moving ref.
PREFIX_BLOB = "579e2b526daf98baf19af879980d78b8002f6cab"
PREFIX_SHA256 = "0e34667aba5f463e28d98ea698f144555dc218cd1644cdbd9577ec334ddd82b2"


def _prefix_html_bytes() -> bytes:
    """The page exactly as it shipped before the affordance fix (blob 579e2b52, at 07eeadc).

    Verified by content hash, not merely referenced: if the object ever resolves to
    something else this fails loudly rather than quietly testing the wrong page. Raising
    rather than skipping is deliberate -- a negative control that does not run is worse
    than not having one, because the suite still reports green for a claim it never checked.
    """
    r = subprocess.run(
        ["git", "cat-file", "blob", PREFIX_BLOB], cwd=REPO, capture_output=True
    )
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(
            f"cannot read the pinned pre-fix blob {PREFIX_BLOB}, so the negative control "
            f"cannot run. CI needs actions/checkout with fetch-depth: 0.\n"
            f"{r.stderr.decode(errors='replace').strip()}"
        )
    got = hashlib.sha256(r.stdout).hexdigest()
    if got != PREFIX_SHA256:
        raise RuntimeError(
            f"the pinned pre-fix blob is not the page it claims to be: {got} != {PREFIX_SHA256}"
        )
    return r.stdout


@pytest.fixture(scope="module")
def prefix_page(tmp_path_factory, browser):
    """The page as it exists on `main` -- the control the new assertions must reject."""
    tmp = tmp_path_factory.mktemp("ui-prefix")
    old = tmp / "index.html"
    old.write_bytes(_prefix_html_bytes())
    for cp in _boot(tmp / "state", NOT_MY_TURN_PICKS, index_html=old):
        page, ctx = _page(browser, cp.url)
        try:
            yield page, cp
        finally:
            ctx.close()


# ---------------------------------------------------------------------------------------
# measurement helpers -- these do NOT hover, focus, or click anything
# ---------------------------------------------------------------------------------------
BTN = "#bestBody tr.prow:first-child button.mark"
ACT_CELL = "#bestBody tr.prow:first-child td.c-act"


def geometry(page: Page, selector: str = BTN) -> dict:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, f"{selector} has no box at all"
    return box


def paint_at_rest(page: Page, selector: str = BTN) -> dict:
    """Computed paint with the pointer parked off the table and nothing focused."""
    return page.evaluate(
        """(sel) => {
             const e = document.querySelector(sel);
             const c = getComputedStyle(e);
             return {
               borderTopColor: c.borderTopColor,
               borderTopWidth: c.borderTopWidth,
               backgroundColor: c.backgroundColor,
               opacity: c.opacity,
               visibility: c.visibility,
               display: c.display,
               text: e.textContent.trim(),
             };
           }""",
        selector,
    )


def _alpha(css_color: str) -> float:
    """Alpha of an rgb()/rgba() computed colour. `transparent` computes to rgba(...,0)."""
    if css_color.startswith("rgba"):
        return float(css_color.split(",")[-1].strip(" )"))
    return 1.0 if css_color.startswith("rgb") else 0.0


def undo_state(page: Page) -> dict:
    return page.evaluate(
        """() => {
             const b = document.getElementById('undoBtn');
             return {present: !!b && !b.hidden, disabled: !!b.disabled,
                     label: b ? b.textContent.trim() : null};
           }"""
    )


def fresh(page: Page) -> None:
    """Reload so `takenStack` starts empty. Marks already sent to the server stay made;
    only the client-side undo stack resets, which is exactly the isolation these tests
    need to make a claim about ONE action."""
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#bestBody tr.prow button.mark", timeout=20_000)
    page.wait_for_function(
        "() => document.getElementById('undoBtn').disabled === true", timeout=20_000
    )


def board_names(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        "#bestBody tr.prow .pname", "els => els.map(e => e.textContent.trim())"
    )


def click_like_a_human(page: Page, dx: int = HUMAN_AIM_SLOP) -> None:
    """Real mouse input at real coordinates, aimed the way a person aims.

    NOT `locator.click()`: that resolves the element and synthesises a click at its exact
    centre, so it succeeds against a 1x1 invisible control and proves nothing about
    whether the thing can be hit. This aims at the centre of the ACTION CELL and then
    misses by `dx` px, which a real target absorbs and a pixel-hunt does not.
    """
    cell = geometry(page, ACT_CELL)
    x = cell["x"] + cell["width"] / 2 + dx
    y = cell["y"] + cell["height"] / 2
    page.mouse.move(x, y)
    page.mouse.click(x, y)


# ---------------------------------------------------------------------------------------
# 1. SIZE FLOOR
# ---------------------------------------------------------------------------------------
def test_row_action_button_meets_the_desktop_size_floor(live) -> None:
    page, _ = live
    box = geometry(page)
    assert box["height"] >= MIN_H, f"button is {box['height']}px tall, floor is {MIN_H}"
    assert box["width"] >= MIN_W, f"button is {box['width']}px wide, floor is {MIN_W}"


# ---------------------------------------------------------------------------------------
# 2. VISIBLE AT REST -- the assertion that would have caught the original bug
# ---------------------------------------------------------------------------------------
def test_row_action_button_is_visible_without_hover_or_focus(live) -> None:
    """No hover, no focus, no click has touched this row. It must already be painted."""
    page, _ = live
    p = paint_at_rest(page)
    assert p["display"] != "none" and p["visibility"] == "visible"
    assert float(p["opacity"]) == 1.0, f"opacity {p['opacity']} at rest"
    assert _alpha(p["borderTopColor"]) > 0, (
        f"border is invisible at rest: {p['borderTopColor']}"
    )
    assert p["borderTopWidth"] != "0px", "border has no width at rest"
    assert _alpha(p["backgroundColor"]) > 0, (
        f"background is invisible at rest: {p['backgroundColor']}"
    )
    assert p["text"], "the control carries no label"


# ---------------------------------------------------------------------------------------
# 3. THE LABEL FLIPS WITH THE CLOCK
# ---------------------------------------------------------------------------------------
def test_button_reads_taken_when_the_next_mark_is_not_mine(live) -> None:
    page, cp = live
    nm = cp.state()["next_mark"]
    assert nm["is_mine"] is False, nm
    assert paint_at_rest(page)["text"] == "TAKEN"


def test_button_reads_draft_him_when_the_next_mark_is_mine(on_the_clock) -> None:
    """The label is driven by where the NEXT MARK LANDS, not by `draft.started`.

    League B reports `pre_draft` through an entire hand-mirrored round, so the old gate
    was false exactly when the distinction mattered. This fixture is still `pre_draft`.
    """
    page, cp = on_the_clock
    st = cp.state()
    assert st["next_mark"] == {"pick_no": 8, "slot": 8, "is_mine": True}, st["next_mark"]

    p = paint_at_rest(page)
    assert p["text"] == "DRAFT HIM"
    # a DIFFERENT control, not the same button relabelled: filled --safe, not outlined
    assert "is-draft" in page.eval_on_selector(BTN, "e => e.className")
    assert p["backgroundColor"] == "rgb(70, 207, 156)", p["backgroundColor"]
    box = geometry(page)
    assert box["width"] >= 118, box


def test_the_label_flips_to_draft_him_on_the_next_render(browser, tmp_path_factory) -> None:
    """Six picks in, the next mark lands on seat 7 -- not mine. Mark one player and the
    next one lands on seat 8, so every row must flip to DRAFT HIM without a reload."""
    tmp = tmp_path_factory.mktemp("ui-flip")
    for cp in _boot(tmp, 6):
        page, ctx = _page(browser, cp.url)
        try:
            assert cp.state()["next_mark"] == {"pick_no": 7, "slot": 7, "is_mine": False}
            assert paint_at_rest(page)["text"] == "TAKEN"

            click_like_a_human(page)
            page.wait_for_function(
                "() => document.querySelector('#bestBody tr.prow button.mark')"
                "  .textContent.trim() === 'DRAFT HIM'",
                timeout=15_000,
            )
            assert cp.state()["next_mark"] == {"pick_no": 8, "slot": 8, "is_mine": True}
            labels = page.eval_on_selector_all(
                "#bestBody tr.prow button.mark",
                "els => [...new Set(els.map(e => e.textContent.trim()))]",
            )
            assert labels == ["DRAFT HIM"], labels
        finally:
            ctx.close()


def test_draft_him_works_pre_draft(browser, tmp_path_factory) -> None:
    """THE reason Fix 3 exists. League 6012 sits in `pre_draft` for the whole of a
    hand-mirrored round, so the old `started && picks_until_me === 0` gate was false
    exactly when the distinction mattered and every row read TAKEN permanently."""
    tmp = tmp_path_factory.mktemp("ui-predraft")
    for cp in _boot(tmp, 7, status="pre_draft"):
        page, ctx = _page(browser, cp.url)
        try:
            st = cp.state()
            assert st["draft"]["started"] is False, "fixture must be pre-draft"
            assert st["clock"]["picks_until_me"] == 0
            assert st["next_mark"]["is_mine"] is True, st["next_mark"]
            assert paint_at_rest(page)["text"] == "DRAFT HIM"
        finally:
            ctx.close()


# ---------------------------------------------------------------------------------------
# FIX 4. THE BOARD MUST NOT MOVE WHEN THE GRAB LIST CHANGES LENGTH
# ---------------------------------------------------------------------------------------
def _route_grab(page, n: int) -> None:
    """Serve /api/state with exactly n grab_now rows. The only way to drive the grab list
    to a chosen length without reaching into the model."""
    def handler(route):
        body = route.fetch().json()
        body["grab_now"] = [dict(p) for p in (body.get("best_available") or [])[:n]]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    page.route("**/api/state*", handler)


def test_best_available_does_not_move_when_the_grab_list_empties(browser, live) -> None:
    """THE assertion for Fix 4. #grabPanel used to change height on every mark and
    #bestPanel is flex:1, so the board jumped 101px under the cursor mid-aim."""
    _, cp = live
    ctx = browser.new_context(viewport=DESKTOP, has_touch=False)
    page = ctx.new_page()
    try:
        page.goto(cp.url, wait_until="domcontentloaded")
        page.wait_for_selector("#bestBody tr.prow button.mark", timeout=20_000)
        top = "() => document.getElementById('bestPanel').getBoundingClientRect().top"

        _route_grab(page, 5)
        page.wait_for_function(
            "() => document.querySelectorAll('#grabBody tr.prow').length === 5", timeout=15_000)
        page.wait_for_timeout(250)
        full = page.evaluate(top)

        page.unroute("**/api/state*")
        _route_grab(page, 0)
        page.wait_for_function(
            "() => document.querySelectorAll('#grabBody tr.prow').length === 0", timeout=15_000)
        page.wait_for_timeout(250)
        empty = page.evaluate(top)

        assert full == empty, (
            f"#bestPanel moved {empty - full:+.2f}px when the grab list emptied "
            f"(full={full}, empty={empty})"
        )
        # and the reservation is real, not an accident of both being collapsed
        assert page.evaluate(
            "() => document.getElementById('grabPanel').getBoundingClientRect().height"
        ) > 150
    finally:
        ctx.close()


def test_undo_fits_inside_its_panel_header(live) -> None:
    """Raising Undo to the new 96x40 floor made it overhang a 29px .phead by 6px top and
    5px bottom, sitting across the panel border. Controls live inside their container."""
    page, _ = live
    box = page.evaluate(
        """() => { const h = document.querySelector('#grabPanel .phead').getBoundingClientRect();
                   const u = document.getElementById('undoBtn').getBoundingClientRect();
                   return {over_top: h.top - u.top, over_bottom: u.bottom - h.bottom}; }"""
    )
    assert box["over_top"] <= 0.5, box
    assert box["over_bottom"] <= 0.5, box


# ---------------------------------------------------------------------------------------
# PART 4. SORTABLE COLUMNS
# ---------------------------------------------------------------------------------------
SORTABLE = [("cons", "consensus_rank", 1), ("vorp", "vorp_rank", 1),
            ("opp", "opp_rank", 1), ("surv", "survival", -1)]


def _col(page, key: str):
    """The values currently rendered, read from the payload the rows were built from."""
    return page.evaluate(
        """(k) => [...document.querySelectorAll('#bestBody tr.prow')].map(r => {
             const cells = {cons: 3, vorp: 4, opp: 5, surv: 6};
             return r.children[cells[k]].textContent.trim();
           })""", key)


def test_each_column_sorts_and_reverses(live) -> None:
    page, _ = live
    fresh(page)
    for key, _field, _best_dir in SORTABLE:
        th = page.locator(f"#bestPanel thead th[data-sort='{key}']")
        th.click()
        page.wait_for_timeout(250)
        first = _col(page, key)[:1]
        assert page.locator(f"#bestPanel thead th[data-sort='{key}'].sorted").count() == 1, key
        arrow = th.locator(".sarrow").inner_text()
        assert arrow in ("▲", "▼"), f"{key}: no direction arrow"

        th.click()                                      # second click reverses
        page.wait_for_timeout(250)
        rev = _col(page, key)[:1]
        assert page.locator(f"#bestPanel thead th[data-sort='{key}'].sorted").count() == 1
        assert th.locator(".sarrow").inner_text() != arrow, f"{key}: arrow did not flip"
        assert first != rev, f"{key}: reversing changed nothing ({first} vs {rev})"

    page.locator("#sortReset").click()
    page.wait_for_timeout(250)
    assert page.locator("#bestPanel thead th.sorted").count() == 0
    assert page.locator("#sortReset").is_hidden()


def test_sorting_by_value_puts_the_true_extreme_first(live) -> None:
    page, _ = live
    fresh(page)
    page.locator("#bestPanel thead th[data-sort='vorp']").click()
    page.wait_for_timeout(250)
    vals = [int(v) for v in _col(page, "vorp") if v]
    assert vals == sorted(vals), "ascending sort is not ascending"
    page.locator("#bestPanel thead th[data-sort='vorp']").click()
    page.wait_for_timeout(250)
    vals = [int(v) for v in _col(page, "vorp") if v]
    assert vals == sorted(vals, reverse=True), "reversed sort is not descending"
    page.locator("#sortReset").click()


def test_marking_after_a_resort_marks_that_row(live) -> None:
    """The row a button belongs to must survive a re-sort -- otherwise sorting is a trap."""
    page, _ = live
    fresh(page)
    page.locator("#bestPanel thead th[data-sort='opp']").click()
    page.wait_for_timeout(300)
    victim = page.locator("#bestBody tr.prow:first-child .pname").inner_text().strip()

    click_like_a_human(page)
    page.wait_for_function(
        "name => !Array.from(document.querySelectorAll('#bestBody .pname'))"
        "  .some(e => e.textContent.trim() === name)", arg=victim, timeout=10_000)
    assert undo_state(page)["label"] == f"Undo: {victim}", undo_state(page)
    page.locator("#undoBtn").click()
    page.wait_for_timeout(400)
    page.locator("#sortReset").click()


def test_sorting_does_not_move_the_panels(live) -> None:
    page, _ = live
    fresh(page)
    top = "() => document.getElementById('bestPanel').getBoundingClientRect().top"
    before = page.evaluate(top)
    for key, _f, _d in SORTABLE:
        page.locator(f"#bestPanel thead th[data-sort='{key}']").click()
        page.wait_for_timeout(150)
        assert page.evaluate(top) == before, f"sorting by {key} moved the board"
    page.locator("#sortReset").click()
    page.wait_for_timeout(200)
    assert page.evaluate(top) == before


def test_the_gap_column_is_present_and_sortable(live) -> None:
    page, _ = live
    fresh(page)
    th = page.locator("#bestPanel thead th[data-sort='gap']")
    assert th.count() == 1
    # inner_text() applies text-transform:uppercase; the source text is "vs ESPN"
    assert th.inner_text().strip().upper().startswith("VS ESPN")
    th.click()
    page.wait_for_timeout(250)
    assert page.locator("#bestPanel thead th[data-sort='gap'].sorted").count() == 1
    page.locator("#sortReset").click()


# ---------------------------------------------------------------------------------------
# C2. THE HELP PANEL
# ---------------------------------------------------------------------------------------
FLAG_TERMS = ["opp+80", "opp-28", "riser", "faller", "vac+15%",
              "rookie:offense", "R1.008", "need"]


def test_help_panel_opens_from_a_button_and_from_the_key(live) -> None:
    page, _ = live
    fresh(page)
    assert page.evaluate("() => document.getElementById('helpPanel').hidden") is True

    page.locator("#legendToggle").click()
    assert page.evaluate("() => document.getElementById('helpPanel').hidden") is False
    page.locator("#helpClose").click()
    assert page.evaluate("() => document.getElementById('helpPanel').hidden") is True

    page.keyboard.press("?")            # a shortcut alone is not an affordance, but it must work
    assert page.evaluate("() => document.getElementById('helpPanel').hidden") is False
    page.keyboard.press("Escape")
    assert page.evaluate("() => document.getElementById('helpPanel').hidden") is True


def test_opening_help_does_not_move_the_board(live) -> None:
    """Same discipline as the Grab now fix: nothing the reader opens may shift the board."""
    page, _ = live
    fresh(page)
    top = "() => document.getElementById('bestPanel').getBoundingClientRect().top"
    before = page.evaluate(top)
    page.locator("#legendToggle").click()
    page.wait_for_timeout(200)
    during = page.evaluate(top)
    page.locator("#helpClose").click()
    page.wait_for_timeout(200)
    after = page.evaluate(top)
    assert before == during == after, f"board moved: {before} -> {during} -> {after}"


def test_help_panel_is_readable_and_complete(live) -> None:
    page, _ = live
    fresh(page)
    page.locator("#legendToggle").click()
    page.wait_for_timeout(200)

    style = page.evaluate(
        """() => { const c = getComputedStyle(document.getElementById('helpCard'));
                   return {fs: parseFloat(c.fontSize), color: c.color}; }"""
    )
    assert style["fs"] >= 12.5, style
    # --txt-2 (154,162,177) or brighter; --txt-3 (106,114,128) is too dim to qualify
    rgb = [int(v) for v in style["color"].strip("rgb()").split(",")[:3]]
    assert min(rgb) >= 154, f"help text dimmer than --txt-2: {style['color']}"

    text = page.locator("#helpCard").inner_text()
    for col in ("Rank", "Value", "Usage", "Lasts"):
        assert col in text, f"help panel omits the {col} column"
    for flag in FLAG_TERMS:
        assert flag in text, f"help panel omits the {flag!r} signal"
    page.locator("#helpClose").click()


def test_column_headers_are_words(live) -> None:
    page, _ = live
    heads = page.eval_on_selector_all(
        "#bestPanel thead th.num", "els => els.map(e => e.textContent.trim())"
    )
    assert heads == ["Rank", "Value", "Usage", "Lasts", "vs ESPN"], heads
    # every one carries the three-part tooltip, not a bare phrase
    for i in range(5):
        t = page.eval_on_selector_all(
            "#bestPanel thead th.num", "els => els.map(e => e.getAttribute('title'))"
        )[i]
        for part in ("WHAT IT IS:", "WHAT THE NUMBER MEANS:", "WHAT TO DO:"):
            assert part in t, f"header {heads[i]} tooltip missing {part}"
        for banned in ("VORP", "replacement level", "marginal", "z-score", "expected value"):
            assert banned.lower() not in t.lower(), f"{heads[i]} tooltip uses banned {banned!r}"


# ---------------------------------------------------------------------------------------
# FIX 2. THE REASONING COLUMN HAS TO BE READABLE
# ---------------------------------------------------------------------------------------
def test_signals_and_numbers_are_legible(live) -> None:
    page, _ = live
    sig = page.evaluate(
        """() => { const c = getComputedStyle(document.querySelector('#bestBody .c-flags'));
                   return {fs: parseFloat(c.fontSize), ff: c.fontFamily, color: c.color}; }"""
    )
    assert sig["fs"] >= 12.5, sig
    assert "Condensed" not in sig["ff"], sig["ff"]
    # --txt-2 (#9aa2b1), one step up from the --txt-3 (#6a7280) it used to be
    assert sig["color"] == "rgb(154, 162, 177)", sig["color"]

    num = page.evaluate(
        "() => parseFloat(getComputedStyle(document.querySelector('#bestBody .c-vorp')).fontSize)"
    )
    assert num >= 14, num


# ---------------------------------------------------------------------------------------
# 4. MOUSE ONLY, END TO END
# ---------------------------------------------------------------------------------------
def test_a_real_mouse_click_marks_the_player(live) -> None:
    page, _ = live
    fresh(page)
    before = board_names(page)
    victim = before[0]
    assert undo_state(page)["disabled"] is True

    click_like_a_human(page)
    page.wait_for_function(
        "name => !Array.from(document.querySelectorAll('#bestBody .pname'))"
        "  .some(e => e.textContent.trim() === name)",
        arg=victim, timeout=10_000,
    )

    u = undo_state(page)
    assert u["present"] and u["disabled"] is False
    # takenStack lives in a closure; its depth is observable exactly here.
    assert u["label"] == f"Undo: {victim}", u["label"]
    assert victim not in board_names(page)


# ---------------------------------------------------------------------------------------
# 5. DOUBLE CLICK MARKS ONCE
# ---------------------------------------------------------------------------------------
def test_row_double_click_marks_exactly_once(live) -> None:
    """One undo must clear it. If the dblclick pushed two entries, one undo leaves the
    button enabled and the second name still on the stack."""
    page, _ = live
    fresh(page)
    victim = board_names(page)[0]
    row = page.locator("#bestBody tr.prow").first
    box = row.bounding_box()
    assert box is not None
    # aim at the NAME end of the row, far from the action button
    page.mouse.dblclick(box["x"] + 60, box["y"] + box["height"] / 2)

    page.wait_for_function(
        "name => !Array.from(document.querySelectorAll('#bestBody .pname'))"
        "  .some(e => e.textContent.trim() === name)",
        arg=victim, timeout=10_000,
    )
    assert undo_state(page)["label"] == f"Undo: {victim}"

    page.locator("#undoBtn").click()
    page.wait_for_function(
        "() => document.getElementById('undoBtn').disabled === true", timeout=10_000
    )
    assert undo_state(page)["disabled"] is True, "one undo did not clear one double-click"


# ---------------------------------------------------------------------------------------
# F3. THE CONFIRMATION LANDS WHERE THE CLICK DID
# ---------------------------------------------------------------------------------------
def test_the_cell_confirms_the_mark_before_the_row_leaves(live) -> None:
    """#actionNote is a small grey string in a panel header. The click happened here."""
    page, _ = live
    fresh(page)
    # freeze the poll so the row cannot be reconciled away before we read the flash
    page.keyboard.press(" ")
    flashed = page.evaluate(
        """(slop) => new Promise(resolve => {
             const td = document.querySelector('#bestBody tr.prow td.c-act');
             const b = td.querySelector('button.mark');
             const r = td.getBoundingClientRect();
             const seen = [];
             const obs = new MutationObserver(() =>
               seen.push({text: b.textContent.trim(), done: b.classList.contains('is-done')}));
             obs.observe(b, {attributes: true, childList: true, subtree: true});
             b.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
             setTimeout(() => { obs.disconnect(); resolve(seen); }, 400);
           })""",
        HUMAN_AIM_SLOP,
    )
    page.keyboard.press(" ")
    assert any(s["done"] for s in flashed), f"the cell never entered its done state: {flashed}"
    assert any(s["text"] in ("TAKEN", "DRAFTED") for s in flashed), flashed


# ---------------------------------------------------------------------------------------
# 6. UNDO IS FURNITURE, NOT A SURPRISE
# ---------------------------------------------------------------------------------------
def test_undo_is_present_and_disabled_at_load_then_named(live) -> None:
    page, _ = live
    fresh(page)

    u = undo_state(page)
    assert u["present"], "Undo must not be hidden at load -- it would move when first used"
    assert u["disabled"] is True
    assert u["label"] == "Undo"

    box = geometry(page, "#undoBtn")
    assert box["height"] >= MIN_H and box["width"] >= MIN_W, box

    victim = board_names(page)[0]
    click_like_a_human(page)
    page.wait_for_function(
        "() => document.getElementById('undoBtn').disabled === false", timeout=10_000
    )
    assert undo_state(page)["label"] == f"Undo: {victim}"


# ---------------------------------------------------------------------------------------
# F6. THE PHONE MUST NOT REGRESS
# ---------------------------------------------------------------------------------------
PHONE = {"width": 393, "height": 852}


def test_the_phone_targets_do_not_shrink(browser, tmp_path_factory) -> None:
    """Everything above is desktop, and desktop rules can reach the phone by specificity.

    This caught a real one: an unscoped `#undoBtn{min-height:30px}` is (1,0,0) and beat
    the touch block's `.btn{min-height:44px}` (0,1,0), shrinking the phone's Undo to 30px.
    """
    tmp = tmp_path_factory.mktemp("ui-phone")
    for cp in _boot(tmp, NOT_MY_TURN_PICKS):
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        try:
            page.goto(cp.url, wait_until="domcontentloaded")
            page.wait_for_selector("#bestBody tr.prow button.mark", timeout=20_000)

            mark = geometry(page)
            assert mark["height"] >= 44, f"touch mark target shrank to {mark['height']}px"
            assert mark["width"] >= 44, f"touch mark target shrank to {mark['width']}px"

            for sel in ("#thumbUndo", "#thumbBoard", "#thumbRoster", "#thumbRuns"):
                b = geometry(page, sel)
                assert b["height"] >= 44, f"{sel} is {b['height']}px tall"

            undo = geometry(page, "#undoBtn")
            assert undo["height"] >= 44, f"the phone's Undo shrank to {undo['height']}px"

            assert page.locator("#thumbBar").is_visible(), "the thumb bar must still show"
        finally:
            ctx.close()


# ---------------------------------------------------------------------------------------
# ENTER MUST NOT MARK OFF A HIDDEN, STALE BOARD
# ---------------------------------------------------------------------------------------
def test_enter_does_not_mark_off_a_hidden_stale_board(browser, live) -> None:
    """The failure this closes: the feed goes bad mid-draft with a query in the box.

    `renderCentre` hides #bestPanel and clears S.nav/S.sel, but the rows it rendered last
    time are still children of #bestBody -- and `enterTarget` fell back to
    `body.firstElementChild`. One Enter would then mark a player off a stale, invisible
    board, at the exact moment you are typing fastest.
    """
    _, cp = live
    ctx = browser.new_context(viewport=DESKTOP, has_touch=False)
    page = ctx.new_page()
    posts: list[str] = []
    page.on(
        "request",
        lambda r: posts.append(r.url) if r.method == "POST" and "/api/taken" in r.url else None,
    )
    try:
        page.goto(cp.url, wait_until="domcontentloaded")
        page.wait_for_selector("#bestBody tr.prow button.mark", timeout=20_000)

        # a real query, still matching real rows (the box holds focus on load)
        page.keyboard.type("Player 01")
        page.wait_for_function(
            "() => document.querySelectorAll('#bestBody tr.prow').length > 0", timeout=10_000
        )

        # now the server starts reporting an unusable board
        def not_ready(route):
            body = route.fetch().json()
            body["board_ready"] = False
            route.fulfill(
                status=200, content_type="application/json", body=json.dumps(body)
            )

        page.route("**/api/state*", not_ready)
        page.wait_for_function(
            "() => document.getElementById('bestPanel').hidden === true", timeout=15_000
        )

        # the precondition that makes this bug possible: hidden panel, rows still in the DOM
        stale = page.eval_on_selector_all("#bestBody tr.prow", "els => els.length")
        assert stale > 0, "precondition failed: no stale rows left to mark off"
        assert undo_state(page)["disabled"] is True

        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)

        assert posts == [], f"Enter marked off a hidden board: {posts}"
        # takenStack lives in a closure; a disabled Undo is depth 0.
        assert undo_state(page)["disabled"] is True, "something reached takenStack"

        # WHY THAT ALONE PROVES LITTLE, AND WHAT ACTUALLY HOLDS IT UP.
        # Today the mark is blocked twice over, and neither block is the guard:
        #   * #q lives INSIDE #bestPanel, so hiding the panel blurs the box -- measured:
        #     document.activeElement becomes <body>. `isTyping` is false, so Enter never
        #     reaches enterTarget(); it falls to `case "Enter"`, where S.sel was nulled.
        #   * renderEnterHint() is called from inside renderCentre AFTER the early return,
        #     so the hint is not re-rendered when the board is unready either.
        # Both are accidents of structure, one DOM move from being false. So exercise the
        # condition the guard actually exists for: the search box reachable while the
        # payload still says the board is not usable.
        assert page.evaluate("() => document.activeElement.tagName") == "BODY"

        page.keyboard.press(" ")  # pause polling so the panel cannot be re-hidden under us
        page.evaluate(
            """() => { document.getElementById('bestPanel').hidden = false;
                       document.getElementById('q').focus(); }"""
        )
        assert page.evaluate("() => document.activeElement.id") == "q"
        assert page.eval_on_selector_all("#bestBody tr.prow", "e => e.length") > 0

        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)

        assert posts == [], (
            "Enter marked a player off a board the payload says is not usable: " + str(posts)
        )
        assert undo_state(page)["disabled"] is True, "something reached takenStack"
    finally:
        ctx.close()


# ---------------------------------------------------------------------------------------
# 7. NEGATIVE CONTROL -- 1, 2 and 4 must FAIL against the page as it ships on main
# ---------------------------------------------------------------------------------------
def test_negative_control_the_prefix_page_fails_1_2_and_4(prefix_page) -> None:
    """A test that passes against the broken page is not a test.

    This asserts the three load-bearing checks REJECT `git show main:...index.html`.
    """
    page, _ = prefix_page
    failures = []

    box = geometry(page)
    if box["height"] < MIN_H or box["width"] < MIN_W:
        failures.append(f"1-size: {box['width']}x{box['height']}")

    p = paint_at_rest(page)
    if _alpha(p["borderTopColor"]) == 0 or _alpha(p["backgroundColor"]) == 0:
        failures.append(
            f"2-paint: border={p['borderTopColor']} bg={p['backgroundColor']}"
        )

    before = board_names(page)
    victim = before[0]
    click_like_a_human(page)
    page.wait_for_timeout(1500)
    if victim in board_names(page):
        failures.append(f"4-mouse: a {HUMAN_AIM_SLOP}px-off click did not mark anybody")

    assert len(failures) == 3, (
        "the pre-fix page should fail all three checks; it failed "
        f"{len(failures)}: {failures}"
    )
