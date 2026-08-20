"""The cockpit is interactive -- driven in a real browser, not asserted by inspection.

Why this exists: a bug report said the cockpit "renders and does not respond to clicks".
Nothing in the Python test suite could have caught that, because every existing server test
asserts on the JSON contract and the page is 1,500 lines of inline JS behind it. A page that
paints and then throws before its handlers bind looks exactly like a working app.

So this suite boots the real FastAPI app against a synthetic board -- no network, no cache,
no Sleeper -- and drives the real page in Chromium. It is deliberately behaviour-level: it
asserts what a person at a keyboard on draft night would do, and it fails if any of those
gestures stops working.

Run it::

    uv run --with playwright playwright install chromium     # once
    uv run --with playwright pytest tests/test_cockpit_ui.py

Playwright is pulled in with ``--with`` rather than declared in ``pyproject.toml``: one test
file needs it, nothing that ships does, and it has no business in the lockfile the draft
-night image resolves from. This file skips itself when Playwright or its browser is absent,
so a plain ``uv run pytest`` stays green on a machine that has neither -- except under
``AUDIBLE_UI_REQUIRED=1``, which CI sets, where a skip is a failure.

``AUDIBLE_UI_CHROMIUM=/path/to/chrome`` uses an already-installed browser instead of the
exact build Playwright's wheel expects.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import closing

import pytest

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.service import CockpitService
from audible.server import create_app

# B6 (the silent-empty class) applies to test suites too: a UI suite that skips itself
# reports green for a claim nobody made. In CI, AUDIBLE_UI_REQUIRED=1 turns every skip in
# this file into a failure, so "the cockpit is interactive" is either proven or red.
UI_REQUIRED = os.environ.get("AUDIBLE_UI_REQUIRED") == "1"


def _unavailable(reason: str):
    if UI_REQUIRED:
        pytest.fail(f"AUDIBLE_UI_REQUIRED=1 but the UI suite cannot run: {reason}")
    pytest.skip(reason)


try:
    from playwright import sync_api as playwright_api
except ImportError:  # pragma: no cover - the optional dependency is genuinely optional
    if UI_REQUIRED:
        raise
    playwright_api = None
    pytest.skip(
        "Playwright is an optional UI-test dependency: uv run --with playwright pytest ...",
        allow_module_level=True,
    )

POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]


def _entry(i: int) -> DraftEntry:
    pos = POSITIONS[(i - 1) % len(POSITIONS)]
    return DraftEntry(
        player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
        eligible_positions=frozenset({pos}), team="XX", model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=(i % 17 == 0), scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i), adp_rank=i, value=0, flags=("riser",) if i % 5 == 0 else (),
    )


def _free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def cockpit(
    tmp_path_factory: pytest.TempPathFactory, sleeper_config: LeagueConfig
) -> Iterator[str]:
    """A real uvicorn serving the real app over a synthetic board."""
    import uvicorn

    svc = CockpitService(
        sleeper_config, state_dir=tmp_path_factory.mktemp("cockpit"), slot_override=4
    )
    svc.board = DraftBoard("sleeper_boyfun", [_entry(i) for i in range(1, 201)])
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = 4
    svc.session.slot_source = "override"
    svc.health.last_success = time.time()

    port = _free_port()
    # warm=False: warming builds a board from the network, and this suite must never
    # depend on one. start() is skipped for the same reason -- no poll loop, no upstream.
    config = uvicorn.Config(
        create_app(svc, warm=False), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        if not thread.is_alive():
            raise RuntimeError("cockpit server thread died during startup")
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("cockpit server did not start within 30s")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def page(cockpit: str) -> Iterator[object]:
    """A loaded cockpit page that fails the test on any console error or uncaught throw.

    The failure this whole file exists for shows up here and nowhere else: an exception
    during handler binding leaves a fully painted, completely inert page.
    """
    with playwright_api.sync_playwright() as pw:
        # AUDIBLE_UI_CHROMIUM lets an image that already ships a Chromium be used as-is.
        # Playwright otherwise insists on the exact build number its wheel was cut against,
        # which turns "the browser is right there" into a skipped suite.
        launch_kwargs = {}
        if executable := os.environ.get("AUDIBLE_UI_CHROMIUM"):
            launch_kwargs["executable_path"] = executable
        try:
            browser = pw.chromium.launch(**launch_kwargs)
        except Exception as exc:  # pragma: no cover - environment without the browser binary
            _unavailable(f"Chromium is not installed for Playwright: {exc}")
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
        pg = ctx.new_page()
        problems: list[str] = []
        pg.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}")
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: problems.append(f"uncaught: {e}"))
        pg.on("requestfailed", lambda r: problems.append(f"request failed: {r.url}"))
        pg.goto(cockpit, wait_until="networkidle")
        pg.wait_for_selector("#bestBody tr.prow", timeout=15_000)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()
        assert not problems, "the page reported errors:\n  " + "\n  ".join(problems)


def _rows(page) -> list[str]:
    return page.eval_on_selector_all(
        "#bestBody tr.prow", "els => els.map(e => e.getAttribute('data-id'))"
    )


def _action_note(page) -> str:
    return page.inner_text("#actionNote").strip()


# ── it renders at all ────────────────────────────────────────────────────────


def test_the_board_renders(page) -> None:
    assert len(_rows(page)) > 20
    assert page.locator("#tabs button").count() > 0
    for control in ("#pauseBtn", "#q"):
        assert page.locator(control).is_visible()


# ── the target-size defect this suite was written for ────────────────────────


def test_the_mark_control_is_a_reachable_target(page) -> None:
    """It was 18x18 and transparent until hover. Both halves of that are the bug."""
    box = page.locator("#bestBody tr.prow").first.locator("button.mark").bounding_box()
    assert box is not None
    assert box["width"] >= 24, f"mark button is only {box['width']}px wide"
    assert box["height"] >= 20, f"mark button is only {box['height']}px tall"
    # visible at rest, without hovering: a control you cannot see is one you do not click
    border = page.eval_on_selector(
        "#bestBody tr.prow button.mark",
        "el => getComputedStyle(el).borderTopColor",
    )
    assert "rgba(0, 0, 0, 0)" not in border and border != "transparent"


def test_mark_buttons_are_not_in_the_tab_order(page) -> None:
    """150 rows of focusable buttons is 150 tab stops between the search box and anything."""
    tabbable = page.eval_on_selector_all(
        "#bestBody button.mark", "els => els.filter(e => e.tabIndex >= 0).length"
    )
    assert tabbable == 0


# ── click semantics: select is not mark, and that is deliberate ──────────────


def test_single_click_selects_and_does_not_mark(page) -> None:
    before = _rows(page)
    target = before[3]
    page.click(f"#bestBody tr.prow[data-id='{target}']")
    row = page.locator(f"#bestBody tr.prow[data-id='{target}']")
    assert "sel" in (row.get_attribute("class") or "")
    assert _rows(page) == before, "a single click must never remove a player from the board"


def test_double_click_marks_the_row(page) -> None:
    before = _rows(page)
    target = before[5]
    name = page.inner_text(f"#bestBody tr.prow[data-id='{target}'] .pname")
    page.dblclick(f"#bestBody tr.prow[data-id='{target}']")
    page.wait_for_function(
        "id => !document.querySelector(`#bestBody tr.prow[data-id='${id}']`)", arg=target
    )
    assert name in _action_note(page)


def test_double_click_on_the_button_marks_exactly_once(page) -> None:
    """Three handlers now reach markTaken. One gesture must still be one mark, or undo
    silently needs two presses and the second fails against a restored player."""
    target = _rows(page)[2]
    page.dblclick(f"#bestBody tr.prow[data-id='{target}'] button.mark")
    page.wait_for_function(
        "id => !document.querySelector(`#bestBody tr.prow[data-id='${id}']`)", arg=target
    )
    page.click("#undoBtn")
    page.wait_for_function(
        "id => !!document.querySelector(`#bestBody tr.prow[data-id='${id}']`)", arg=target
    )
    # one undo was enough, so exactly one mark was recorded
    assert page.locator("#undoBtn").is_hidden()


def test_the_mark_button_marks_and_undo_restores(page) -> None:
    before = _rows(page)
    target = before[1]
    page.click(f"#bestBody tr.prow[data-id='{target}'] button.mark")
    page.wait_for_function(
        "id => !document.querySelector(`#bestBody tr.prow[data-id='${id}']`)", arg=target
    )
    page.click("#undoBtn")
    page.wait_for_function(
        "id => !!document.querySelector(`#bestBody tr.prow[data-id='${id}']`)", arg=target
    )
    assert _rows(page) == before, "undo must be a true inverse, not an approximate one"


# ── the primary draft-night path ─────────────────────────────────────────────


def test_search_then_enter_marks_the_named_top_match(page) -> None:
    page.click("#q")
    page.fill("#q", "Player 012")
    page.wait_for_selector("#enterHint:not([hidden])")
    hint = page.inner_text("#enterHint")
    assert "Player 012" in hint, f"the Enter target must be named before you commit: {hint!r}"
    page.press("#q", "Enter")
    page.wait_for_function("() => !document.querySelector(\"#bestBody tr.prow[data-id='p012']\")")
    assert page.input_value("#q") == "", "a stale query filters the board to a player who left it"
    assert page.evaluate("() => document.activeElement.id") == "q", "focus must stay in the box"
    assert "Player 012" in _action_note(page)


def test_t_marks_the_selected_row(page) -> None:
    target = _rows(page)[4]
    page.click(f"#bestBody tr.prow[data-id='{target}']")
    page.keyboard.press("t")
    page.wait_for_function(
        "id => !document.querySelector(`#bestBody tr.prow[data-id='${id}']`)", arg=target
    )


def test_pause_responds(page) -> None:
    page.click("#pauseBtn")
    assert page.locator("#pauseBtn").get_attribute("aria-pressed") == "true"
    page.click("#pauseBtn")
    assert page.locator("#pauseBtn").get_attribute("aria-pressed") == "false"
